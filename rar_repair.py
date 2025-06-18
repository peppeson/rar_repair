#!/usr/bin/env python3
"""
A web interface to repair RAR archives on a Synology NAS using .rev files.
It provides a file browser, initiates the `rar rc` command, and streams the output
in real-time to the web UI. It includes features to cancel the running process
and shut down the server directly from the interface.

---

Interfaccia web per riparare archivi RAR su un Synology NAS utilizzando file .rev.
Fornisce un esplora file, avvia il comando `rar rc` e trasmette l'output in tempo
reale all'interfaccia web. Include funzionalità per annullare il processo
in esecuzione e spegnere il server direttamente dall'interfaccia.

Autore: Giuseppe Montana
"""

import http.server
import socketserver
import urllib.parse
import subprocess
import os
import json
import threading
import time
import queue
from pathlib import Path
from socketserver import ThreadingTCPServer

PORT = 8080
RAR_PATH = "/usr/local/bin/rar"
ROOT_PATH = "/volume1"

streaming_sessions = {}

class RARRepairHandler(http.server.BaseHTTPRequestHandler):
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = self.get_main_page()
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        elif self.path.startswith('/browse'):
            self.handle_browse_request()
        elif self.path.startswith('/stream/'):
            self.handle_stream_request()
        else:
            self.send_error(404)
    
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)

        if self.path == '/shutdown':
            self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({"message": "Server in fase di spegnimento..."}).encode('utf-8'))
            threading.Thread(target=self.server.shutdown).start()
        
        elif self.path == '/repair':
            rev_file = params.get('rev_file', [''])[0].strip()
            if not rev_file:
                self.send_json_response({"success": False, "error": "File non specificato"}); return
            session_id = self.start_repair_stream(rev_file)
            self.send_json_response({"success": True, "session_id": session_id})

        elif self.path == '/cancel':
            session_id = params.get('session_id', [''])[0].strip()
            if not session_id or session_id not in streaming_sessions:
                self.send_json_response({"success": False, "error": "Sessione non valida o scaduta."}); return

            session = streaming_sessions.get(session_id)
            process_to_kill = session.get('process')

            if process_to_kill and process_to_kill.poll() is None:
                try:
                    process_to_kill.terminate()
                    session['queue'].put("\n\n🛑 Riparazione annullata dall'utente.\n")
                    self.send_json_response({"success": True, "message": "Processo annullato"})
                except Exception as e:
                    self.send_json_response({"success": False, "error": str(e)})
            else:
                self.send_json_response({"success": False, "error": "Processo non in esecuzione o già terminato."})
        
        else:
            self.send_error(404)

    def handle_browse_request(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        path = params.get('path', [ROOT_PATH])[0]
        filter_type = params.get('filter', ['all'])[0]
        
        if not os.path.abspath(path).startswith(os.path.abspath(ROOT_PATH)):
            path = ROOT_PATH
        
        result = self.browse_directory(path, filter_type)
        self.send_json_response(result)
    
    def browse_directory(self, path, filter_type='all'):
        try:
            if not os.path.exists(path) or not os.path.isdir(path):
                return {"success": False, "error": "Directory non trovata"}
            
            items = []
            
            if path != ROOT_PATH:
                parent_path = os.path.dirname(path)
                items.append({
                    "name": "..",
                    "type": "parent",
                    "path": parent_path
                })
            
            try:
                entries = sorted(os.listdir(path))
            except PermissionError:
                return {"success": False, "error": "Permessi insufficienti"}
            
            for entry in entries:
                if entry.startswith('@'):
                    continue
                entry_path = os.path.join(path, entry)
                
                try:
                    if os.path.isdir(entry_path):
                        items.append({
                            "name": entry,
                            "type": "directory",
                            "path": entry_path
                        })
                    elif os.path.isfile(entry_path):
                        show_file = False
                        file_ext = entry.lower()
                        
                        if filter_type == 'all':
                            show_file = True
                        elif filter_type == 'rar' and (file_ext.endswith('.rar') or '.part' in file_ext):
                            show_file = True
                        elif filter_type == 'rev' and file_ext.endswith('.rev'):
                            show_file = True
                        
                        if show_file:
                            items.append({
                                "name": entry,
                                "type": "file",
                                "path": entry_path,
                                "size": os.path.getsize(entry_path)
                            })
                except (PermissionError, OSError):
                    continue
            
            breadcrumb = self.create_breadcrumb(path)
            
            return {
                "success": True,
                "path": path,
                "items": items,
                "breadcrumb": breadcrumb
            }
            
        except Exception as e:
            return {"success": False, "error": f"Errore: {str(e)}"}
    
    def create_breadcrumb(self, path):
        breadcrumb = []
        current_path = ROOT_PATH
        
        breadcrumb.append({"name": "volume1", "path": ROOT_PATH})
        
        if path != ROOT_PATH:
            relative_parts = os.path.relpath(path, ROOT_PATH).split(os.sep)
            for part in relative_parts:
                if part and part != '.':
                    current_path = os.path.join(current_path, part)
                    breadcrumb.append({"name": part, "path": current_path})
        
        return breadcrumb
    
    def start_repair_stream(self, rev_file):
        import uuid
        session_id = str(uuid.uuid4())
        
        output_queue = queue.Queue()
        streaming_sessions[session_id] = {"queue": output_queue, "process": None}
        
        thread = threading.Thread(
            target=self.run_repair_with_streaming,
            args=(rev_file, output_queue, session_id)
        )
        thread.daemon = True
        thread.start()
        
        return session_id
    
    def run_repair_with_streaming(self, rev_file, output_queue, session_id):
        process = None
        try:
            if not os.path.exists(rev_file):
                output_queue.put(f"❌ Errore: File non trovato: {rev_file}\n")
                output_queue.put("__DONE__")
                return
            
            if not rev_file.lower().endswith('.rev'):
                output_queue.put(f"❌ Errore: Il file deve avere estensione .rev\n")
                output_queue.put("__DONE__")
                return
            
            if not os.path.exists(RAR_PATH):
                output_queue.put(f"❌ Errore: RAR non trovato in {RAR_PATH}\n")
                output_queue.put("__DONE__")
                return
            
            output_queue.put(f"🔧 Avvio riparazione RAR\n")
            output_queue.put(f"📁 File: {rev_file}\n")
            output_queue.put(f"⏰ Inizio: {time.strftime('%H:%M:%S')}\n")
            output_queue.put("-" * 50 + "\n")
            
            cmd = [RAR_PATH, "rc", rev_file]
            work_dir = os.path.dirname(rev_file)
            
            output_queue.put(f"$ {' '.join(cmd)}\n")
            output_queue.put(f"📂 Directory: {work_dir}\n\n")
            
            process = subprocess.Popen(
                cmd,
                cwd=work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            streaming_sessions[session_id]['process'] = process
            
            while True:
                line = process.stdout.readline()
                if not line:
                    break
                output_queue.put(line)
            
            return_code = process.wait()
            
            output_queue.put("\n" + "=" * 50 + "\n")
            if return_code == 0:
                output_queue.put("✅ Riparazione completata con successo!\n")
            elif return_code == -9 or return_code == -15:
                 output_queue.put("✅ Processo terminato.\n")
            else:
                output_queue.put(f"❌ Riparazione fallita (codice: {return_code})\n")
            
            output_queue.put(f"⏰ Fine: {time.strftime('%H:%M:%S')}\n")
            
        except Exception as e:
            output_queue.put(f"\n❌ Errore imprevisto: {str(e)}\n")
        finally:
            output_queue.put("__DONE__")
            threading.Timer(300, lambda: streaming_sessions.pop(session_id, None)).start()

    def handle_stream_request(self):
        session_id = self.path.split('/')[-1]
        
        session_data = streaming_sessions.get(session_id)
        if not session_data:
            self.send_error(404)
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        output_queue = session_data['queue']
        
        try:
            while True:
                try:
                    data = output_queue.get(timeout=1)
                    
                    if data == "__DONE__":
                        self.wfile.write(f"event: done\ndata: \n\n".encode())
                        break
                    
                    import json
                    escaped_data = json.dumps(data)
                    self.wfile.write(f"data: {escaped_data}\n\n".encode())
                    self.wfile.flush()
                    
                except queue.Empty:
                    self.wfile.write(f"event: heartbeat\ndata: \n\n".encode())
                    self.wfile.flush()
                    
        except (ConnectionResetError, BrokenPipeError):
            pass
    
    def send_json_response(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def get_main_page(self):
        return """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RAR Repair Tool - Synology NAS</title>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            position: relative;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        
        .shutdown-container {
            position: absolute;
            top: 15px;
            right: 15px;
        }
        .shutdown-btn {
            background: #6c757d;
            color: white;
            border: none;
            border-radius: 10%;
            width: 36px;
            height: 36px;
            font-size: 18px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: background-color 0.2s;
        }
        .shutdown-btn:hover {
            background: #5a6268;
        }
        
        .browser-section { margin-bottom: 30px; border: 2px solid #e0e0e0; border-radius: 8px; overflow: hidden; }
        .browser-header { background: #f8f9fa; padding: 15px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
        .breadcrumb { display: flex; align-items: center; gap: 5px; }
        .breadcrumb-item { color: #007bff; cursor: pointer; text-decoration: none; }
        .breadcrumb-item:hover { text-decoration: underline; }
        .breadcrumb-separator { margin: 0 5px; color: #666; }
        
        .filter-buttons { display: flex; gap: 10px; }
        .filter-btn { padding: 5px 12px; border: 1px solid #ccc; background: #0056b3; border-radius: 4px; cursor: pointer; font-size: 12px; }
        .filter-btn.active { background: #007bff; color: white; border-color: #007bff; }
        
        .file-list { max-height: 300px; overflow-y: auto; }
        .file-item { display: flex; align-items: center; padding: 10px 15px; border-bottom: 1px solid #f0f0f0; cursor: pointer; transition: background-color 0.2s; }
        .file-item:hover { background-color: #f8f9fa; }
        .file-item.selected { background-color: #e3f2fd; }
        
        .file-icon { width: 20px; margin-right: 10px; text-align: center; }
        .file-name { flex: 1; font-weight: 500; }
        .file-size { color: #666; font-size: 12px; margin-left: 10px; }
        
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }
        input[type="text"] { width: 100%; padding: 12px; border: 2px solid #ddd; border-radius: 5px; font-size: 14px; }
        input[type="text"]:focus { border-color: #007bff; outline: none; }
        
        .action-buttons {
            display: flex;
            gap: 10px;
            align-items: center;
        }
        button {
            background-color: #007bff;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            min-width: 120px;
        }
        button:hover { background-color: #0056b3; }
        button:disabled { background-color: #ccc; cursor: not-allowed; }
        
        #cancelBtn {
            background-color: #dc3545;
            display: none;
        }
        #cancelBtn:hover {
            background-color: #c82333;
        }
        
        .terminal { margin-top: 20px; background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 13px; line-height: 1.4; max-height: 400px; overflow-y: auto; white-space: pre-wrap; display: none; }
        .terminal.active { display: block; }
        
        .info { background-color: #d1ecf1; border: 1px solid #bee5eb; color: #0c5460; margin-bottom: 20px; padding: 15px; border-radius: 5px; }
        
        .loading { display: inline-block; width: 20px; height: 20px; border: 3px solid #f3f3f3; border-top: 3px solid #007bff; border-radius: 50%; animation: spin 1s linear infinite; margin-right: 10px; }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="shutdown-container">
            <button class="shutdown-btn" id="shutdownBtn" title="Ferma il server">🛑</button>
        </div>
        
        <h1>🔧 RAR Repair Tool</h1>
        
        <div class="info">
            <strong>Come usare:</strong><br>
            1. Naviga nelle cartelle e seleziona un file .rev<br>
            2. Oppure inserisci manualmente il percorso<br>
            3. Clicca "Ripara Archivio" e monitora il progresso<br>
            4. Se necessario, puoi annullare la riparazione in corso
        </div>
        
        <div class="browser-section">
            <div class="browser-header">
                <nav class="breadcrumb" id="breadcrumb">
                    <span class="breadcrumb-item" data-path="/volume1">volume1</span>
                </nav>
                <div class="filter-buttons">
                    <button class="filter-btn active" data-filter="all">Tutti</button>
                    <button class="filter-btn" data-filter="rar">RAR</button>
                    <button class="filter-btn" data-filter="rev">REV</button>
                </div>
            </div>
            <div class="file-list" id="fileList">
                <div style="padding: 20px; text-align: center; color: #666;">
                    <div class="loading"></div>
                    Caricamento file...
                </div>
            </div>
        </div>
        
        <form id="repairForm">
            <div class="form-group">
                <label for="revFile">File selezionato:</label>
                <input type="text" id="revFile" name="rev_file" placeholder="Seleziona un file dal browser sopra o inserisci il percorso" required>
            </div>
            
            <div class="action-buttons">
                <button type="submit" id="repairBtn">Ripara Archivio</button>
                <button type="button" id="cancelBtn">Annulla Riparazione</button>
            </div>
        </form>
        
        <div id="terminal" class="terminal"></div>
    </div>

    <script>
        let currentPath = '/volume1';
        let currentFilter = 'all';
        let selectedFile = '';
        let currentSessionId = null;

        document.addEventListener('DOMContentLoaded', function() {
            setupEventListeners();
            setTimeout(() => loadDirectory(currentPath), 100);
        });
        
        function setupEventListeners() {
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                    this.classList.add('active');
                    currentFilter = this.dataset.filter;
                    loadDirectory(currentPath);
                });
            });
            
            document.getElementById('repairForm').addEventListener('submit', function(e) {
                e.preventDefault();
                startRepair();
            });

            document.getElementById('shutdownBtn').addEventListener('click', function() {
                if (confirm('Sei sicuro di voler fermare il server? Questa operazione è irreversibile.')) {
                    fetch('/shutdown', { method: 'POST' })
                        .then(() => {
                            document.body.innerHTML = '<div style="padding: 50px; text-align: center; font-size: 1.2em;"><h1>Server fermato.</h1><p>Puoi chiudere questa finestra.</p></div>';
                        })
                        .catch(error => {
                            console.error('La richiesta di shutdown ha causato un errore (normale, il server si è spento):', error);
                            document.body.innerHTML = '<div style="padding: 50px; text-align: center; font-size: 1.2em;"><h1>Server fermato.</h1><p>Puoi chiudere questa finestra.</p></div>';
                        });
                }
            });
            
            document.getElementById('cancelBtn').addEventListener('click', cancelRepair);
        }
        
        async function loadDirectory(path) {
            const fileListEl = document.getElementById('fileList');
            fileListEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;"><div class="loading"></div>Caricamento file...</div>';
            
            try {
                const response = await fetch(`/browse?path=${encodeURIComponent(path)}&filter=${currentFilter}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const result = await response.json();
                
                if (result.success) {
                    currentPath = result.path;
                    updateBreadcrumb(result.breadcrumb);
                    updateFileList(result.items);
                } else {
                    fileListEl.innerHTML = `<div style="padding: 20px; text-align: center; color: red;">❌ Errore: ${result.error}</div>`;
                }
            } catch (error) {
                fileListEl.innerHTML = `<div style="padding: 20px; text-align: center; color: red;">❌ Errore di connessione: ${error.message}</div>`;
            }
        }
        
        function updateBreadcrumb(breadcrumb) {
            const breadcrumbEl = document.getElementById('breadcrumb');
            breadcrumbEl.innerHTML = '';
            
            breadcrumb.forEach((item, index) => {
                if (index > 0) {
                    const sep = document.createElement('span');
                    sep.className = 'breadcrumb-separator';
                    sep.textContent = '>';
                    breadcrumbEl.appendChild(sep);
                }
                const link = document.createElement('span');
                link.className = 'breadcrumb-item';
                link.textContent = item.name;
                link.dataset.path = item.path;
                link.addEventListener('click', () => loadDirectory(item.path));
                breadcrumbEl.appendChild(link);
            });
        }
        
        function updateFileList(items) {
            const fileListEl = document.getElementById('fileList');
            fileListEl.innerHTML = '';
            
            if (!items || items.length === 0) {
                fileListEl.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">📁 Cartella vuota</div>';
                return;
            }
            
            items.forEach(item => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                
                let icon = '';
                if (item.type === 'parent') icon = '⬆️';
                else if (item.type === 'directory') icon = '📁';
                else {
                    if (item.name.toLowerCase().endsWith('.rev')) icon = '🔧';
                    else if (item.name.toLowerCase().endsWith('.rar') || item.name.includes('.part')) icon = '📦';
                    else icon = '📄';
                }
                
                fileItem.innerHTML = `
                    <div class="file-icon">${icon}</div>
                    <div class="file-name">${item.name}</div>
                    ${item.size ? `<div class="file-size">${formatFileSize(item.size)}</div>` : ''}
                `;
                
                fileItem.addEventListener('click', () => {
                    if (item.type === 'directory' || item.type === 'parent') {
                        loadDirectory(item.path);
                    } else {
                        selectFile(item.path, fileItem);
                    }
                });
                fileListEl.appendChild(fileItem);
            });
        }
        
        function selectFile(path, element) {
            document.querySelectorAll('.file-item').forEach(item => item.classList.remove('selected'));
            element.classList.add('selected');
            selectedFile = path;
            document.getElementById('revFile').value = path;
        }
        
        function formatFileSize(bytes) {
            if (bytes === 0) return '0 B';
            const units = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(1024));
            return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
        }
        
        async function startRepair() {
            const revFile = document.getElementById('revFile').value.trim();
            const terminal = document.getElementById('terminal');
            if (!revFile) { alert('Seleziona un file .rev prima di avviare la riparazione.'); return; }
            
            const repairBtn = document.getElementById('repairBtn');
            const cancelBtn = document.getElementById('cancelBtn');
            
            repairBtn.disabled = true;
            repairBtn.innerHTML = '<div class="loading"></div>Riparando...';
            cancelBtn.style.display = 'inline-block';
            terminal.innerHTML = '';
            terminal.classList.add('active');
            
            try {
                const response = await fetch('/repair', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'rev_file=' + encodeURIComponent(revFile)
                });

                if (!response.ok) {
                    throw new Error(`Errore dal server: ${response.status} ${response.statusText}`);
                }
                
                const result = await response.json();
                
                if (result.success) {
                    currentSessionId = result.session_id;
                    connectToStream(result.session_id);
                } else {
                    terminal.textContent = `Errore durante l'avvio: ${result.error || 'Errore sconosciuto.'}`;
                    resetUI();
                }
            } catch (error) {
                terminal.textContent = `Errore di connessione: ${error.message}`;
                resetUI();
            }
        }
        
        async function cancelRepair() {
            if (!currentSessionId) return;
            const cancelBtn = document.getElementById('cancelBtn');
            cancelBtn.disabled = true;
            cancelBtn.textContent = 'Annullamento...';
            
            try {
                const response = await fetch('/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'session_id=' + encodeURIComponent(currentSessionId)
                });
                if (!response.ok) {
                    throw new Error(`Errore dal server: ${response.status} ${response.statusText}`);
                }
                const result = await response.json();
                if (!result.success) {
                    const terminal = document.getElementById('terminal');
                    terminal.textContent += `❌ Errore durante l'annullamento: ${result.error}`;
                }
            } catch (error) {
                const terminal = document.getElementById('terminal');
                terminal.textContent += `❌ Errore di rete durante l'annullamento: ${error.message}`;
                resetUI();
            }
        }
        
        function connectToStream(sessionId) {
            const terminal = document.getElementById('terminal');
            const eventSource = new EventSource(`/stream/${sessionId}`);
            
            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                terminal.textContent += data;
                terminal.scrollTop = terminal.scrollHeight;
            };
            
            eventSource.addEventListener('done', function(event) {
                eventSource.close();
                resetUI();
            });
            
            eventSource.onerror = function(event) {
                eventSource.close();
                terminal.textContent += '❌ Connessione interrotta';
                resetUI();
            };
        }
        
        function resetUI() {
            const repairBtn = document.getElementById('repairBtn');
            const cancelBtn = document.getElementById('cancelBtn');

            repairBtn.disabled = false;
            repairBtn.textContent = 'Ripara Archivio';

            cancelBtn.style.display = 'none';
            cancelBtn.disabled = false;
            cancelBtn.textContent = 'Annulla Riparazione';
            
            currentSessionId = null;
        }

        function shutdownServer() {
            if (confirm('Sei sicuro di voler fermare il server?')) {
                fetch('/shutdown', { method: 'POST' })
                .finally(() => {
                    document.body.innerHTML = '<div style="padding: 50px; text-align: center; font-size: 1.2em;"><h1>Server fermato.</h1><p>Puoi chiudere questa finestra.</p></div>';
                });
            }
        }
    </script>
</body>
</html>"""

    def log_message(self, format, *args):
        pass

def main():
    print("=== RAR Repair Tool per Synology NAS (v3) ===")
    print(f"Avvio server su porta {PORT}...")
    if not os.path.exists(RAR_PATH): print(f"⚠️  ATTENZIONE: RAR non trovato in {RAR_PATH}")
    else: print(f"✅ RAR trovato in {RAR_PATH}")
    if not os.path.exists(ROOT_PATH): print(f"⚠️  ATTENZIONE: {ROOT_PATH} non trovato")
    else: print(f"✅ Directory root: {ROOT_PATH}")
    try:
        with ThreadingTCPServer(("", PORT), RARRepairHandler) as httpd:
            print(f"✅ Server avviato con successo!")
            print(f"🌐 Accedi a: http://localhost:{PORT} o http://[IP-DEL-NAS]:{PORT}")
            print("💡 Premi il pulsante 🛑 nell'interfaccia web per fermare il server.")
            print("-" * 50)
            httpd.serve_forever()
            print("\n🛑 Server fermato tramite interfaccia web.")
    except KeyboardInterrupt: print("\n🛑 Server fermato dall'utente (Ctrl+C)")
    except PermissionError: print(f"❌ Errore: Porta {PORT} non disponibile. Un altro servizio la sta usando?")
    except Exception as e: print(f"❌ Errore imprevisto: {e}")

if __name__ == "__main__":
    main()