### Certifikaty
- Python (ssl modul) nepodporuje priamo .pfx/.p12 súbory, je preto potrebné extrahovať:
  - certifikat (vratane CA certifikatov):
    ```
    openssl pkcs12 -in <PFX FILE> -nokeys -noenc -passin pass:<PASSWORD> -out cert.crt
    ```
  - privatny kluc: 
	```
	openssl pkcs12 -in <PFX FILE> -nocerts -noenc  -passin pass:<PASSWORD> | openssl rsa -outform PEM -out key.pem
  	```
- Pre úspešný TLS handshake je potrebné overiť certifikát servera OKTE, vrátane celého CA reťazca. Je mozne ho:
  - stiahnut z [webu OKTE](https://www.okte.sk/sk/informacie/oznamy/2025-02-13-vymena-serveroveho-certifikatu-okte-sk-dna-4-3-2025)
  - získať cez OpenSSL:
    ```
    openssl s_client -connect isot.okte.sk:443 -showcerts
    ```
    všetky (3) certifikáty (CA chain) vložte do jedného .pem súboru, napríklad `okte_cert.pem` v strukture:
    ```
    -----BEGIN CERTIFICATE-----
    ...
    -----END CERTIFICATE-----
    -----BEGIN CERTIFICATE-----
    ...
    -----END CERTIFICATE-----
    -----BEGIN CERTIFICATE-----
    ...
    -----END CERTIFICATE-----
### Python
- Tetovane na verzi **Python 3.13.3** 
- potrebne nainstalovat kniznicu **websockets**, pomocou prikazu:
  ```
  pip install websockets
  ```
### Spustenie a pouzitie
```
python okte-websocket-client.py -h
```
- Zobrazi:
```
usage: okte-websocket-client.py [-h] --username USERNAME --password PASSWORD --client-cert CLIENT_CERT --client-key CLIENT_KEY
                                --okte-ca OKTE_CA [--output-dir OUTPUT_DIR] [--auto-save AUTO_SAVE] [--send-request-periodically SEND_REQUEST_PERIODICALLY] [--debug]
options:
  -h, --help            				show this help message and exit
  --username USERNAME   				(required) Meno
  --password PASSWORD   				(required) Heslo
  --client-cert CLIENT_CERT				(required) Cesta ku klientskému certifikátu
  --client-key CLIENT_KEY				(required) Cesta k privátnemu kľúču
  --okte-ca OKTE_CA     				(required) Cesta k serverovému OKTE certifikátu
  --output-dir OUTPUT_DIR				Adresár pre ukladanie snapshotov (default: orderbook-snapshots)
  --auto-save AUTO_SAVE					Interval pre automatické ukladanie snapshotu v sekundách (0 = vypnuté) (default: 60)
  --send-request-periodically SEND_REQUEST_PERIODICALLY	Periodické posielanie požiadavky na snapshot každých X sekúnd (default: vypnuté)
  --debug               				Zobrazovať debug výpisy do konzoly
```
- **Priklad pouzitia:**
```
python okte-websocket-client.py --username $USERNAME --password $PASSWORD --client-cert cert.crt --client-key key.pem --okte-ca okte_ccert.pem --output-dir orderbook-snapshots --auto-save 10 --send-request-periodically 60
```
Toto spustenie ziskava a uklada aktualnu knihu objednavok kazdych 10 sekund do priecinka orderbook-snapshots, nazov kazdeho snapsotu je `orderbook_snapshot-autosave_<timestamp>.json`, zaroven posiela preventivny request kazdych 60 sekund na ziskanie knihy objednavok (vynuluje sekvenciu, nie je potrebne, je vhodne na testovanie)
- **Funkcionalita:**
  - Po spusteni skriptu sa zobrazia moznosti pre manualne zasahy (optional):
    - `"Zadaj príkaz ('send', 'save' alebo 'exit'):"`
      - **send** -> jednorazove poslanie requestu na ziskanie knihy objednavok (tak ako to automaticky robi send-request-periodically)
      - **save** -> jednorazove ulozenie knihy objednavok v aktualnom case (tak ako to robi auto-save), ulozi do suboru s nazvom `orderbook_snapshot_<timestamp>.json`
      - **exit** -> ukonci vykonavanie skriptu 
- **Websocket rozhranie OKTE:** 
  - Tak ako je uvedene v [dokumentacii](https://okte.sk/media/5xkepcls/isot_technicka_specifikacia_externych_rozhrani_systemu_ut_1_19_upgradevdt_final.pdf) rozhranie je dostupne pomocou GET volania `wss://isot.okte.sk:8443/api/v1/idm/ws?topics=orderbook`
  - Z dokumentacie: `topics=orderbook` -> zmeny knihy objednávok. Knihu objednavok (**orderbook-snapshot (E08-01)**) klient obdrží automaticky pri prvom pripojení s `topic=orderbook` alebo na základe vlastnej požiadavky o obnovenie orderbook-snapshot. Websocket spojenie zostava otvorene a klient prijima dalej uz len zmeny v knihe objednavok (**orderbook-change (E12-02)**). 
  - Tieto zmeny (orderbook-change) sa zachytavaju a real-time aktualizuju knihu objednavok udrziavanu v pamati (premenna `orderbook_state`). Netreba tak zahlcovat sluzbu neustalymi poziadavkami na orderbook-snapshot (veľký dátový objem, velky pocet requestov), staci len prijimat spravy a aplikovat zmeny (male datove objekty).
  - Na zaklade testovania sa drviva vacsina zmien tyka `buyChanges`, `sellChanges` a `statistics` pre jedntlive periody, a preto boli tieto zmeny implementovane v skripte, ostatne zmeny (`ownStatistics`, `BlockOrderChanges`) implementovane nie su (aktualne sa da riesit manualnym poslanim `send`, pripadne nastavenim `send-request-periodically`, cim sa ziska nova kniha objednavok aj s tymito aplikovanymi zmenami). Skript tieto pripady loguje: `"Nespracované zmeny v change_period: <zmeny>, pre aktualizáciu týchto zmien zadajte 'send'"`.
