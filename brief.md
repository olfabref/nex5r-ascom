# Projet : piloter un Sony NEX-5R depuis N.I.N.A. (ASCOM Alpaca)

## Objectif

Contrôler un Sony NEX-5R depuis N.I.N.A. pour l'astrophoto : déclencher des poses, récupérer les images, et faire l'autofocus de NINA en pilotant la mise au point **d'un objectif E-mount à focus électronique (focus-by-wire)** monté sur l'appareil. L'usage au foyer d'un télescope viendra plus tard.

## Matériel et environnement

- Appareil : Sony NEX-5R (APS-C 16,1 MP, 2012), compatible PlayMemories Camera Apps (PMCA), Wi-Fi intégré.
- Objectif : Sigma 30mm DC DN (E-mount, mise au point électronique). `pmca-console info` le rapporte comme « Model 0xa0c530 », firmware 3.01.
- Boîtier : firmware 1.03.
- Poste de dev : Mac (Intel ou Apple Silicon, à préciser).
- **Attention : N.I.N.A. ne tourne que sous Windows.** Il faudra un PC Windows, une VM ou un mini-PC pour NINA. Le serveur Alpaca, lui, peut tourner n'importe où sur le réseau (Mac, Raspberry Pi, PC).
- Alimentation : le NEX-5R ne s'alimente pas par USB. Prévoir l'adaptateur secteur AC-PW20 (ou fausse batterie) pour une nuit complète.

## Ce qui a été établi (recherches)

1. **Pas de contrôle USB.** Le NEX-5R ne supporte pas le tethering USB : allumé avec le câble, il passe en mode transfert de fichiers. Le driver ASCOM Sony de référence (dougforpres/ASCOMSonyCameraDriver et son plugin NINA) fonctionne **uniquement en USB**, donc il est inutilisable ici.
2. **API Wi-Fi officielle (Sony Camera Remote API via l'app « Smart Remote Control »).** Possible mais limitée : images récupérées en JPEG (RAW resté sur la SD), support du mode Bulb incertain sur ce modèle, et pas de commande de focus pas à pas exploitable par NINA. Écartée comme voie principale.
3. **Voie retenue : app Android embarquée sur l'appareil.**
   - Le projet **Sony-PMCA-RE** (ma1co) permet d'installer des apps Android personnalisées sur les appareils PMCA, dont le NEX-5R.
   - Les apps doivent être compatibles **Android 2.3.7**. Les certificats debug sont acceptés.
   - Les API Sony internes sont accessibles via **OpenMemories: Framework** (exemple : PMCADemo).
   - La classe `CameraEx` expose `startOneShotFocusDrive(direction, vitesse)` (direction `FOCUS_DRIVE_DIRECTION_FAR` / `NEAR`). L'app Smart Remote officielle l'utilise avec une vitesse de 4. Des vitesses trop élevées lèvent une exception.
   - **Risque connu :** sur certains boîtiers (ex. A7 II), `camera.getSupportedParameters()` renvoie `focus-drive-supported=false`. Il faut vérifier sur le NEX-5R.
   - L'app OpenMemories: Tweak permet d'activer telnet et adb sur l'appareil (utile pour le debug).
4. **Code de référence existant :** l'app **FocusBracket** (obs1dium) utilise le pilotage du focus via le framework. L'app **TimeLapse** (jonasjuffinger) est basée dessus et montre le déclenchement en boucle.

## Architecture cible

```
[NEX-5R]                                 [Serveur Alpaca]                [PC Windows]
App Android embarquée  <-- Wi-Fi/HTTP -->  Python (Mac / Pi / PC)  <-- Alpaca -->  N.I.N.A.
 - focus +/- N pas                           - Device "Camera"
 - déclenchement, pose, ISO                  - Device "Focuser"
 - lecture du fichier (JPEG/ARW) sur la SD   - conversion image -> ImageArray
```

### Composant 1 : app embarquée (Java, Android 2.3.7, OpenMemories Framework)

Mini serveur HTTP sur le Wi-Fi de l'appareil. API proposée (à affiner) :

- `GET  /status` : état (prêt, en pose, focus en mouvement), paramètres courants.
- `POST /focus?dir=near|far&steps=N&speed=S` : déplacement relatif du focus.
- `POST /capture?exposure=SEC&iso=ISO` : lance une pose (Bulb si > 30 s, si supporté).
- `GET  /capture/status` : en cours / terminé + nom du dernier fichier.
- `GET  /image/latest?format=raw|jpeg` : renvoie le dernier fichier depuis la carte SD.

### Composant 2 : serveur ASCOM Alpaca (Python)

- Base suggérée : le modèle officiel de device Alpaca en Python d'ASCOM (dépôt `ASCOMInitiative/AlpycaDevice`, à vérifier).
- **Focuser** : la commande caméra est relative et l'objectif est by-wire. Le driver compte les pas lui-même et expose une position absolue simulée (`Absolute=true`, `MaxStep` à calibrer). Mesurer la répétabilité, et utiliser la compensation de jeu (backlash) de NINA.
- **Camera** : ARW décodé avec `rawpy` (données Bayer brutes, `SensorType` couleur + `BayerOffset`) ou JPEG en repli. Exposer `ImageArray`, `StartExposure`, `ImageReady`, gains/ISO.
- Découverte Alpaca (UDP 32227) pour que NINA trouve les deux devices automatiquement.

## Étape en cours

Test de faisabilité du pilotage du focus, sans écrire de code :

1. Installer Sony-PMCA-RE v0.18 sur le Mac (binaires macOS, moins testés que Windows).
   - `xattr -d com.apple.quarantine` + `chmod +x` sur les binaires. Rosetta si Apple Silicon.
   - Appareil en **Connexion USB → MTP** (le mode stockage de masse exige le Camera Driver Sony sur macOS).
   - Fermer Photos, Transfert d'images, Dropbox, Google Drive avant de brancher.
   - `./pmca-console info` pour vérifier la détection.
2. Installer FocusBracket : `./pmca-console install -i`.
3. Objectif en MF, lancer un bracketing. **Si la bague bouge, le focus drive fonctionne sur le NEX-5R → on développe l'app embarquée.**

## Plan B (si `focus-drive-supported=false`)

Focuser mécanique : moteur pas à pas + courroie sur la bague de mise au point, piloté par un Arduino avec un firmware de focuser ASCOM (ex. myFocuserPro2). Fonctionne aussi avec un objectif by-wire en MF. La partie Camera (app embarquée ou API Wi-Fi) reste nécessaire.

## Questions ouvertes

- ~~Le NEX-5R accepte-t-il `startOneShotFocusDrive` ?~~ **Non (2026-11-02)** : la fonction est absente de `/system/framework/sony.cameraex.odex` du NEX-5R (firmware 1.03), d'où le plantage de FocusBracket au lancement. En revanche, `CameraEx.shiftFocusPosition(int pas)` (déplacement relatif, renvoie un booléen) existe ; l'app Sony Bracket Pro, installée sur l'appareil, l'utilise pour son bracketing de mise au point.
- Le bracketing de mise au point de Bracket Pro **fonctionne** avec le Sigma 30mm DC DN (2026-11-02) : `shiftFocusPosition` pilote bien cet objectif, au moins pendant une rafale.
- `shiftFocusPosition` fonctionne-t-il hors d'une rafale (appareil au repos, en MF) ? Combien de pas pour toute la course ? Le déplacement est-il reproductible (aller-retour au même point) ?
- Les poses longues (Bulb) sont-elles accessibles depuis une app embarquée ?
- L'app peut-elle lire les fichiers ARW de la carte SD pendant que l'appareil tourne ?
- Le Wi-Fi reste-t-il stable pendant une nuit entière avec une app custom ?
- ~~Mac Intel ou Apple Silicon ? Quel objectif exact ?~~ Apple Silicon ; Sigma 30mm DC DN.

## Liens

- Sony-PMCA-RE : https://github.com/ma1co/Sony-PMCA-RE
- OpenMemories: Framework : https://github.com/ma1co/OpenMemories-Framework
- PMCADemo : https://github.com/ma1co/PMCADemo
- OpenMemories: Tweak : https://github.com/ma1co/OpenMemories-Tweak
- Liste des apps : https://github.com/ma1co/OpenMemories-AppList
- TimeLapse (exemple) : https://github.com/jonasjuffinger/TimeLapse
- Appareils compatibles : https://openmemories.readthedocs.io/devices.html
- Driver ASCOM Sony USB (non compatible, pour référence) : https://github.com/dougforpres/ASCOMSonyCameraDriver

## Avertissement

Hack non officiel issu de rétro-ingénierie. Risque faible pour une simple app, mais non nul : aucune garantie, ni de Sony ni des auteurs du projet.
