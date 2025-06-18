# RAR Repair Tool – Interfaccia Web per Synology NAS

**Autore:** Giuseppe Montana

## Contesto
Questo strumento è stato creato per risolvere il problema della riparazione di archivi RAR multi-volume direttamente dal NAS Synology (DSM 7.2 o superiore), senza l'uso di un PC esterno o complicate operazioni via SSH.  
Lo scopo è permettere all'utente di avviare manualmente la riparazione usando i file `.rev` quando un download manager (es. JDownloader) segnala parti mancanti.

## Prerequisiti: Installare `rar` e `unrar`
Per funzionare correttamente, lo script richiede la presenza dei comandi `rar` e `unrar` sul NAS.

**Installazione:**
1. **Download:** Scarica “RAR for Linux” da [www.rarlab.com/download.htm](https://www.rarlab.com/download.htm).
2. **Estrai:** Decomprimi il pacchetto `rarlinux-[versione].tar.gz`. Troverai una cartella `rar` con vari file.
3. **Copia su NAS:** Copia solo `rar` e `unrar` nella cartella `/usr/local/bin/` del NAS (usa File Station, SCP o SSH).
4. **Permessi:** Imposta i permessi di esecuzione:
   ```bash
   chmod +x /usr/local/bin/rar
   chmod +x /usr/local/bin/unrar
   ```

:warning: Senza questi file nello specifico percorso, la riparazione non funzionerà.

## Soluzione: Script Python con Interfaccia Web
Uno script Python avvia un mini server web che consente la gestione della riparazione tramite browser.

### Come usarlo
1. Salva lo script in `/volume1/scripts/rar_repair.py`.
2. Crea un'attività manuale nel Task Scheduler DSM per eseguire:
   ```bash
   python3 /volume1/scripts/rar_repair.py
   ```
3. Una volta avviato, accedi all'interfaccia su `http://[IP-DEL-NAS]:8080`.

### Funzionalità dell’interfaccia:
1. **File Browser:** Navigazione tra le cartelle a partire da `/volume1`.
2. **Filtri:** Mostra solo `.rar`, solo `.rev` o tutti i file.
3. **Selezione File:** Cliccando un `.rev`, il percorso viene precompilato nel campo di input.
4. **Avvio Riparazione:** Il comando `rar rc nomefile.rev` viene eseguito in background con output visibile in tempo reale.
5. **Annulla:** È possibile interrompere l’operazione.
6. **Arresto Server:** Tasto per spegnere il server web in sicurezza.

### Vantaggi
- **Interfaccia intuitiva:** Niente riga di comando.
- **Nessuna dipendenza esterna:** Usa solo Python standard (già presente su DSM).
- **Controllo manuale:** Nessun automatismo; tutto è gestito dall’utente.
- **Log in tempo reale:** Verifica immediata dell’esito.
- **Accessibilità totale:** Funziona da PC, tablet o smartphone connessi alla rete locale.

---

# RAR Repair Tool – Web Interface for Synology NAS

**Author:** Giuseppe Montana

## Overview
This tool was created to allow multi-volume RAR archive repair directly from a Synology NAS (DSM 7.2+), without requiring a separate PC or complex SSH operations.  
The goal is to manually start repairs using `.rev` recovery files when a download manager (e.g., JDownloader) reports missing parts.

## Requirements: Install `rar` and `unrar`
To work properly, the script requires the `rar` and `unrar` executables on the NAS.

**Installation Steps:**
1. **Download:** Get “RAR for Linux” from [www.rarlab.com/download.htm](https://www.rarlab.com/download.htm).
2. **Extract:** Unpack `rarlinux-[version].tar.gz` to get the `rar` folder.
3. **Copy to NAS:** Copy only `rar` and `unrar` to `/usr/local/bin/` on the NAS (via File Station, SCP, or SSH).
4. **Set Permissions:**
   ```bash
   chmod +x /usr/local/bin/rar
   chmod +x /usr/local/bin/unrar
   ```

:warning: Without these files in the specified path, the script will not work.

## Solution: Python Script with Web Interface
A Python script runs a lightweight standalone web server, offering an easy-to-use interface to manage RAR repair.

### How to Use
1. Save the script to `/volume1/scripts/rar_repair.py`.
2. Create a manual task in DSM Task Scheduler to run:
   ```bash
   python3 /volume1/scripts/rar_repair.py
   ```
3. Access the interface via `http://[NAS-IP]:8080`.

### Interface Features:
1. **Integrated File Browser:** Browse folders from `/volume1`.
2. **Filtering:** View only `.rar`, only `.rev`, or all files.
3. **File Selection:** Clicking a `.rev` auto-fills its full path.
4. **Start Repair:** Executes `rar rc filename.rev` in the background with real-time output.
5. **Cancel Operation:** Stop the repair process at any time.
6. **Stop Server:** Button to safely shut down the web server.

### Highlights
- **User-Friendly UI:** No command line required.
- **No External Dependencies:** Uses Python’s standard libraries (pre-installed on DSM).
- **Manual Control:** No automation; user decides what to repair and when.
- **Real-Time Feedback:** View logs and repair status instantly.
- **Accessible Anywhere:** Works from PC, tablet, or smartphone on the local network.
