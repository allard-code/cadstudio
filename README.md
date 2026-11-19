# CAD-Studio

CAD-Studio is een parametrische CAD-editor (build123d / OpenCascade, de geometrische kern van FreeCAD) met een 3D-editor in de browser en een **MCP-server**. Claude kan er 3D-printbare modellen mee ontwerpen, ze zelf bekijken en ze exporteren als **multi-color 3MF** voor Anycubic Slicer Next (Kobra S1 + ACE Pro). Orca, Bambu Studio en PrusaSlicer worden ook ondersteund.

```
 Claude Code / Desktop / claude.ai ──MCP (HTTP /mcp)──►┐
                                                       │  CAD-Studio container  ── /data (projecten, exports, inbox)
 jij, overal (browser, telefoon)   ──https (editor /)──►┘
```

Eén proces levert alles:

| Pad | Wat |
|---|---|
| `/` | web-editor (login met token) |
| `/mcp` | MCP-server (streamable HTTP) voor Claude |
| `/dl/...` | ondertekende downloadlinks voor exports, 72 uur geldig |
| `/health` | healthcheck |

Claude en jij werken in hetzelfde project. Wat Claude verandert, zie je direct in de editor, en andersom.

---

## 1. Draaien in Docker (aanbevolen)

### Op je Docker-host (bijv. de DockerVM op Proxmox)

```bash
git clone https://github.com/allard-code/cadstudio.git && cd cadstudio
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # plak dit als CADSTUDIO_TOKEN in .env
nano .env                                                        # zet ook CADSTUDIO_PUBLIC_URL
docker compose up -d --build
```

Open daarna `http://<ip-van-de-host>:8765` en log in met het token. Het bouwen duurt de eerste keer een paar minuten; de image wordt ca. 1 GB, vooral door OpenCascade.

### Via Portainer

- **Stacks → Add stack → Repository**: URL van je git-repo, compose-pad `docker-compose.yml`. Zet onder *Environment variables* `CADSTUDIO_TOKEN` en `CADSTUDIO_PUBLIC_URL`.
- Of gebruik de kant-en-klare image. Na de eerste push naar GitHub bouwt de meegeleverde Action (`.github/workflows/docker-publish.yml`) `ghcr.io/allard-code/cadstudio:latest`. Vervang in de compose `build: .` door `image: ghcr.io/allard-code/cadstudio:latest`, plak de compose in de web-editor van Portainer en klaar. Is het package privé, maak het dan publiek of voeg GHCR toe als registry in Portainer.

### Data

Alles staat in het volume `./data` (in de container: `/data`):

```
data/
├── projects/<project>/project.json   ontwerp (parameters + code per onderdeel)
├── projects/<project>/exports/       3MF / STL / STEP
├── projects/<project>/meshes/        geïmporteerde referentiemodellen
└── inbox/                            zet hier STL/3MF neer om te importeren
```

Tip: koppel `data/` ook aan FileBrowser of een Samba-share. Dan zet je MakerWorld-downloads in `inbox/` en haal je exports direct op. De container draait als `PUID`/`PGID` (standaard 1000:1000) en zet de rechten op `/data` zelf goed.

### Instellingen (environment)

| Variabele | Standaard | Doel |
|---|---|---|
| `CADSTUDIO_TOKEN` | – (verplicht in compose) | toegang tot editor én `/mcp` |
| `CADSTUDIO_PUBLIC_URL` | `http://localhost:8765` | adres in downloadlinks die Claude teruggeeft |
| `CADSTUDIO_PORT` | `8765` | poort in de container |
| `PUID` / `PGID` | `1000` | eigenaar van de bestanden in `data/` |

---

## 2. Koppelen aan Claude Code

### Optie A – als plugin (makkelijkst, werkt in elk project)

Zet deze repo op GitHub. Doe daarna in Claude Code:

```
/plugin marketplace add allard-code/cadstudio
/plugin install cad-studio@cadstudio
```

Claude Code vraagt dan om de **CAD-Studio URL** (bijv. `http://192.168.1.50:8765`) en het **token**. Het token wordt versleuteld opgeslagen. De plugin bevat de MCP-koppeling en de skill `cad-design`, met de werkwijze voor printbare multi-color ontwerpen. Lokaal testen zonder GitHub kan ook: `/plugin marketplace add /pad/naar/cadstudio`.

### Optie B – één commando

```bash
claude mcp add --transport http --scope user cad-studio http://192.168.1.50:8765/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

### Optie C – in deze repo werken

De meegeleverde `.mcp.json` gebruikt de omgevingsvariabelen `CADSTUDIO_URL` en `CADSTUDIO_TOKEN`:

```bash
export CADSTUDIO_URL=http://192.168.1.50:8765
export CADSTUDIO_TOKEN=<TOKEN>
claude          # keur de server 'cad-studio' goed bij de eerste start
```

`CLAUDE.md` beschrijft de codebase, zodat Claude Code direct aan CAD-Studio zelf kan doorontwikkelen.

**Lokale bestanden vanuit Claude Code** (de server staat elders, dus lokale paden werken daar niet). Upload ze zo:

```bash
curl -H "Authorization: Bearer $CADSTUDIO_TOKEN" -F file=@wagon.3mf "$CADSTUDIO_URL/api/import"
```

---

## 3. Overal ("digitaal") gebruiken

| Situatie | Aanpak |
|---|---|
| Thuis op het netwerk | `http://<ip>:8765`, klaar. |
| Onderweg, eigen apparaten (laptop, telefoon) | **Tailscale** op de Docker-host en je apparaten → `http://<tailscale-naam>:8765`. Geen poort open op je router; dit is het veiligst. |
| Vanuit **claude.ai / Claude-app op je telefoon** | De server moet via **HTTPS publiek bereikbaar** zijn, want Claude maakt de verbinding vanuit de cloud van Anthropic. Gebruik een **Cloudflare Tunnel** (`cloudflared`, geen open poorten) of je bestaande reverse proxy met een eigen (sub)domein, bijv. `https://cad.jouwdomein.nl`. Zet `CADSTUDIO_PUBLIC_URL` op dat adres. |

### Toevoegen als custom connector in claude.ai

*Instellingen → Connectors → Add custom connector*, URL `https://cad.jouwdomein.nl/mcp`:

- **Als je account "Request headers" heeft** (bèta, nog niet voor iedereen): header `authorization` = `Bearer <TOKEN>`, of `x-api-key` = `<TOKEN>`.
- **Zonder request headers:** gebruik als URL `https://cad.jouwdomein.nl/mcp?token=<TOKEN>`. Dat werkt, maar het token staat dan in de URL en kan in logs van proxies terechtkomen. Gebruik daarom een lang token en vervang het als je twijfelt.

Daarna werkt CAD-Studio ook in claude.ai en de mobiele app. De editor open je in de browser van je telefoon via dezelfde URL; je logt één keer in en de login wordt 90 dagen onthouden.

> Zet de container nooit publiek zonder `CADSTUDIO_TOKEN`. Onderdeelcode is Python die in de container wordt uitgevoerd. Wie bij `/mcp` of de editor kan, kan dus code in de container draaien. De container draait zonder root-rechten en ziet alleen `/data`, maar behandel het token als een wachtwoord.

---

## 4. Lokaal zonder Docker (Claude Desktop, stdio)

```powershell
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e .
python -m cadstudio web           # editor op http://127.0.0.1:8765 (zonder login)
```

Claude Desktop (`claude_desktop_config.json`, zie `claude_desktop_config.example.json`):

```json
{ "mcpServers": { "cad-studio": {
    "command": "C:\\Users\\<jij>\\cadstudio\\.venv\\Scripts\\python.exe",
    "args": ["-m", "cadstudio", "mcp"] } } }
```

In deze modus start de MCP-server de editor zelf mee.

---

## Wat je Claude kunt vragen

- *"Maak een bakje van 80×50×30 mm met 2 mm wand, afgeronde hoeken en mijn naam in rood als inleg op de voorkant. Exporteer als 3MF."*
- *"Importeer wagon.3mf uit de inbox als referentie en ontwerp een lading die er met 0,3 mm speling in past."*
- *"Maak de wand 1,6 mm en de tekst groter, en laat een preview zien."*

Tools die Claude heeft: `get_project`, `new_project`, `open_project`, `set_params`, `set_part`, `update_part`, `add_primitive`, `delete_part`, `measure`, `render_preview` (Claude ziet zelf een render met 4 aanzichten), `list_inbox`, `import_mesh` (inbox / URL), `export_3mf`, `export_stl` en `export_step` (allemaal met downloadlink), `get_build123d_reference` en `open_editor`.

## De editor

| Onderdeel | Wat het doet |
|---|---|
| Parameters | Variabelen voor alle code (sliders). Hiermee pas je het hele model aan. |
| Onderdelen | Eén onderdeel per kleur of stuk. Oog = zichtbaar, `F2` = filament/ACE-slot. |
| Inspector | Naam, kleur, ACE-slot, positie/rotatie, build123d-code (**Ctrl+Enter** = bouwen), maten, volume, grammen, waterdicht-check. |
| 3D-view | Draaien (links), pannen (rechts), zoomen (scroll), klik = selecteren. **G** = verplaatsen, **X** = X-ray, **E** = randen, **F** = passend. |
| Export | 3MF voor *Anycubic/Orca* of *PrusaSlicer*, als 1 multi-color object of losse objecten. Ook STL en STEP. |
| Import | STL/3MF/OBJ als referentie (wordt gecentreerd op het bed). |

## Multi-color voor de ACE Pro

- **Elke kleur is een eigen onderdeel** met een `filament`-nummer (slot 1–4; 5–8 bij een tweede ACE).
- **Inleg:** trek het kleuronderdeel af van het basisonderdeel (`result = body - part("tekst")`). Zo overlappen de volumes niet.
- **Export "1 object (multi-color)"** geeft elk deel een eigen extruder in `Metadata/model_settings.config`, zoals Bambu Studio en Orca dat ook opslaan. Neemt de slicer de toewijzing niet over, kies dan "losse objecten" of STL's en wijs de slots handmatig toe.
- Bij export controleert CAD-Studio of je meer dan 4 slots gebruikt, of dat één slot onderdelen met verschillende kleuren heeft.

## Beperkingen

- Geen volledige Fusion 360: geen sketch-constraints, tijdlijn of joints. Je modelleert met code en parameters, en juist dat kan Claude goed.
- Geïmporteerde meshes kun je verplaatsen, meten en exporteren, maar je kunt er geen booleans mee doen.
- De Docker-image is alleen voor `linux/amd64` gebouwd.

Gebaseerd op build123d (Apache-2.0), three.js (MIT, meegeleverd in `static/vendor`), FastAPI en de MCP Python SDK.
