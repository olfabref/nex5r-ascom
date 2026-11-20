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
- ~~Le retour à une même valeur est-il reproductible ?~~ **Oui (2026-11-20, Focuser Alpaca)** : poses de 1 s à travers N.I.N.A./Alpaca, netteté (variance du laplacien, plan vert central) sur un objet à 1-3 m. Retour à la position 16 entre 16, 8, 24 : netteté identique à ±15 % (lumière déclinante pendant la série). À ±8 positions, la netteté est divisée par 10 : à cette distance la fenêtre est loin d'être négligeable. Les poses ne déplacent pas la référence. Une première série a donné à 16 une netteté 10× plus faible au premier point qu'au dernier : l'appareil avait été déplacé pendant l'essai.
- **Focuser Alpaca (2026-11-20)** : `camera-app` expose `/focusarm[?mode=]` (autofocus = armement, décalage 0) et `/focus?offset=N` (attend la fin, ~250 ms), refusés avant armement et pendant une pose ; l'événement `onAutoFocusDone` arrive bien après un autofocus logiciel. `alpaca-server` sert un device `Focuser` (IFocuserV4) absolu, positions 0 à 32, armé à la connexion. Armement par défaut : autofocus en `manual` puis passage en `auto` (vérifié via Alpaca : réarmement par l'Action `arm`, puis netteté 1,6e-2 à 16, 1,1e-3 à 8, 4,9e-4 à 24, 1,1e-2 au retour à 16).
- **AF raté en `auto` (2026-11-20, objectif masqué par une feuille unie)** : l'objectif reste au même point, à peu près. Netteté à l'offset 0 avant / après : 1,2e-2 / 8,9e-3 (à ±8 : ~7e-4 dans les deux cas), sous une lumière qui changeait (moyenne 9750 → 12170). L'écart, s'il y en a un, vaut au plus un ou deux pas. La nuit, l'autofocus d'armement sur le ciel ne devrait donc pas perdre la mise au point préalable. À confirmer sur un vrai ciel. Après les armements suivants, `onAutoFocusDone` n'est plus arrivé dans les 3 s (seulement au premier) : l'armement a lieu quand même.
- **Autofocus N.I.N.A. de jour (2026-11-20, N.I.N.A. 3.3 nightly #057, PC Windows → serveur Alpaca sur le Mac)** : **réussi**. Méthode Contrast Detection, ISO 100, 1 s, pas de 2 autour de 16 : balayage 24 → 10, point 26 ajouté, position finale **19**, en environ 5 min (≈30 s par point, dont 13 s de transfert Wi-Fi). Netteté calculée de mon côté sur les mêmes ARW : pic à 18 (pas de 2), cohérent. Trois obstacles rencontrés :
  - ISO 1600 demandé par défaut par N.I.N.A. : images saturées à 98 %, contraste nul. De jour, ISO 100 (ExposureMin = 1 s à cause du Bulb) ;
  - le plugin Hocus Focus remplace l'autofocus de N.I.N.A. et ne connaît que le HFR des étoiles (tout à 0) : choisir l'autofocus NINA dans Options → Imagerie ;
  - l'autofocus par contraste de N.I.N.A. plante sur l'image couleur (« stride 9840 must be >= 29520 ») : `sensor_type = 'mono'` dans `config.toml` envoie les mêmes données Bayer comme monochrome. À remettre en `color` pour la nuit (la détection d'étoiles HFR n'est pas touchée par ce bug).
- La retouche à la bague en `dmf` déplace-t-elle le point de référence ? ~~Un armement en `manual` (objectif immobile) puis un passage en `auto` permet-il de piloter sans que l'autofocus bouge l'objectif ?~~ **Oui (2026-11-20, app relancée, aucun AF depuis l'ouverture)** : netteté à l'offset 0 sans armement 1,06e-2 ; après `/focusarm?mode=manual`, 7,6e-3 à 0 et 4,6e-3 à −8 (petit effet ou simple bruit, la lumière variait) ; puis `/focusmode?value=auto` **sans nouvel AF** : 1,19e-2 à 0, 1,5e-3 à −8, 1,1e-3 à +8, 1,50e-2 au retour à 0. Les décalages pilotent donc l'objectif autour de la position laissée à la main, et l'armement ne la déplace pas. Aucun blocage. C'est la procédure pour la nuit : mise au point approximative à la main, armement en `manual`, passage en `auto`.
- ~~Les poses longues (Bulb) sont-elles accessibles depuis une app embarquée ?~~ **Oui (2026-11-18, page Bulb de `camera-app`)** :
  - mode M par `setSceneMode("manual-exposure")`, puis `decrementShutterSpeed()` (plus lent) jusqu'au-delà de 30" : `getShutterSpeed()` renvoie alors **65535/1** = Bulb ;
  - `takePicture()` ouvre, `cancelTakePicture()` N secondes plus tard ferme : l'EXIF indique **10,0 s et 60,0 s** pour des poses de 10 et 60 s, une seule image ARW + JPEG par pose, présente sur la carte 3 s après la fermeture ;
  - absents du firmware : `OnCaptureStatusListener`, `ExposureCompleteListener`, `StoreImageCompleteListener` et le réglage de réduction de bruit des poses longues. Pas de signal de fin de capture : il faut surveiller l'apparition du fichier dans DCIM ;
  - l'horloge de l'appareil est en 1970 : les dates de fichier ne servent pas à dater les poses.
- ~~L'app peut-elle lire les fichiers ARW de la carte SD pendant que l'appareil tourne ?~~ **Oui (2026-11-18)** : le serveur HTTP de `camera-app` (port 8080) liste DCIM et sert l'ARW (16,3 Mo en 13 s, ~1,2 Mo/s par le Wi-Fi). L'app active elle-même le Wi-Fi (`WifiManager.setWifiEnabled`) et l'appareil rejoint le réseau sans Tweak.
- ~~**Bloquant (2026-11-18) : une pose lancée par logiciel ne part pas.**~~ **Résolu le 2026-11-18 : il faut diffuser `APO/NO` avant la pose.** L'intent `com.android.server.DAConnectionManagerService.apo` avec `apo_info = "APO/NO"` désactive l'extinction automatique. Sans lui, `burstableTakePicture` reste en attente : `onShutter` « annulé » à la fermeture, aucun fichier. Avec lui seul, depuis HTTP et sans aucun appui, `onShutter status 0` arrive en ~250 ms et le fichier est écrit. Isolé par bissection d'un clone de la séquence de l'app TimeLapse 1.4.0 (jonasjuffinger), qui déclenche sur ce boîtier (`/tlshoot`, classe `TlShoot`). Sans effet sur la prise : réglages (`setParameters`, verrou AE, MF, bracketing), `AutoPictureReviewControl`, `Gpelibrary`, `notifyAppInfo`, `startPreview` explicite. Penser à rediffuser `APO/NORMAL` en quittant. NEX5R Dev le fait désormais à chaque lancement : `/capture` en Bulb de 5 s depuis HTTP a donné DSC04103, avec un EXIF à 5,0 s. Historique des impasses (touches simulées, `notifyAppInfo` de Sony, `Caution`, `HandlerThread`, `OpenOptions`, télécommande IR envisagée) : voir l'historique git de ce fichier.
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
