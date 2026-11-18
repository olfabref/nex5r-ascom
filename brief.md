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
- ~~`shiftFocusPosition` fonctionne-t-il hors d'une rafale ?~~ **Oui (2026-11-02, app `camera-app`)** : la mise au point bouge appareil au repos, en mode `auto`, `dmf` et `manual`. Paramètres caméra : `focus-shift-supported=true`, **±16 pas maximum par appel**. Appelée depuis le fil principal (UI) de l'app, la fonction ne rend jamais la main : il faut toujours l'appeler depuis un autre fil.
- **Sémantique confirmée (2026-11-03)** : l'argument est un **décalage absolu** par rapport à un point de référence, borné à [−16, +16], pas un déplacement relatif. Répéter `shift(16)` ne fait rien ; `shift(16)` puis `shift(4)` fait revenir la mise au point. Chaque appel renvoie `true` en 230 à 300 ms.
- **Conditions de fonctionnement (2026-11-03)** :
  - sans autofocus depuis l'ouverture de la caméra, l'appel **bloque indéfiniment** et fige l'appareil (redémarrage obligatoire) ;
  - un autofocus lancé en mode `manual` évite le blocage, mais l'objectif **ne bouge pas** (les appels renvoient pourtant `true`) ;
  - après un **vrai autofocus en mode `auto`**, les décalages font bouger l'objectif en mode `auto`, mais plus après un passage en `manual` ;
  - un changement de mode ne redéfinit pas le point de référence.
  
  Modèle de fonctionnement : comme Bracket Pro, autofocus en mode `auto`, puis décalages de −16 à +16 autour du point trouvé.
- **Mesures (2026-11-03)** : la fenêtre ±16 est **petite** (différence à peine visible sur un objet à 1 m) : les pas sont fins, adaptés à l'affinage de l'autofocus N.I.N.A. Le mode `dmf` se comporte comme `auto`. Après un **autofocus raté** (mur uni), les décalages fonctionnent toujours.
- **Modèle retenu pour le focuser Alpaca** : positions absolues 0 à 32 (= décalage −16 à +16), point 16 = résultat de l'autofocus de l'appareil, lancé une fois pour armer le pilotage. Mise au point approximative préalable : autofocus sur un objet lointain au crépuscule, ou retouche à la bague en `dmf` (à tester).
- Le retour à une même valeur est-il reproductible ? La retouche à la bague en `dmf` déplace-t-elle le point de référence ?
- ~~Les poses longues (Bulb) sont-elles accessibles depuis une app embarquée ?~~ **Oui (2026-11-18, page Bulb de `camera-app`)** :
  - mode M par `setSceneMode("manual-exposure")`, puis `decrementShutterSpeed()` (plus lent) jusqu'au-delà de 30" : `getShutterSpeed()` renvoie alors **65535/1** = Bulb ;
  - `takePicture()` ouvre, `cancelTakePicture()` N secondes plus tard ferme : l'EXIF indique **10,0 s et 60,0 s** pour des poses de 10 et 60 s, une seule image ARW + JPEG par pose, présente sur la carte 3 s après la fermeture ;
  - absents du firmware : `OnCaptureStatusListener`, `ExposureCompleteListener`, `StoreImageCompleteListener` et le réglage de réduction de bruit des poses longues. Pas de signal de fin de capture : il faut surveiller l'apparition du fichier dans DCIM ;
  - l'horloge de l'appareil est en 1970 : les dates de fichier ne servent pas à dater les poses.
- ~~L'app peut-elle lire les fichiers ARW de la carte SD pendant que l'appareil tourne ?~~ **Oui (2026-11-18)** : le serveur HTTP de `camera-app` (port 8080) liste DCIM et sert l'ARW (16,3 Mo en 13 s, ~1,2 Mo/s par le Wi-Fi). L'app active elle-même le Wi-Fi (`WifiManager.setWifiEnabled`) et l'appareil rejoint le réseau sans Tweak.
- **Bloquant (2026-11-18) : une pose lancée par logiciel ne part pas.** `takePicture` n'ouvre l'obturateur que pendant un vrai appui sur le déclencheur (dans le gestionnaire de la touche S2). Depuis HTTP, rien ne part (`onShutter` « annulé » à la fermeture, aucun fichier), à 4" comme en Bulb. Essayé sans succès : `burstableTakePicture`, `startDirectShutter` (déclencheur ou mode, à la TimeLapse), `AutoPictureReviewControl`, `stopPreview`, `setRemoteControlMode(true)` (pire), autofocus logiciel avant la pose (ignoré en mise au point manuelle ; en auto il démarre une fois puis reste bloqué après un échec), écouteurs AF/aperçu de Smart Remote, une mi-course physique juste avant. Sans `takePicture` de l'app, l'appui physique ne produit rien : ce n'est pas le firmware seul qui déclenche. Touches simulées (2026-11-18) : `Instrumentation.sendKeySync` des scan codes S1_1/S1_2/S2 arrive comme un vrai appui (`flags 0x8`) mais la pose est annulée pareil ; le verrou est sous Android (état matériel du bouton). Smart Remote (installé, décompilé avec `dexdump`) déclenche à distance par `burstableTakePicture` via sa machine à états (`actHalfPressShutter` puis `actTakePicture`). Session suivante : Smart Remote et l'app Sony Time-lapse ne font rien de plus qu'un `burstableTakePicture` ; essayé sans effet le `notifyAppInfo` complet de Sony (`CATEGORY_REC`/`STILL` + listes de touches, à chaud et au lancement), et le facteur d'inhibition (`getInhibitionInfo()` = 0 avant la pose). Reste : vérifier avec un téléphone que Smart Remote déclenche bien sur ce boîtier (et lire son logcat), sinon télécommande IR.
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
