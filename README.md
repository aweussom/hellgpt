# HellGPT

> *Profanity, delivered straight from Hell*

A culturally-aware profanity chat assistant delivered as a Discord bot. Based in Hell, Norway — the Gods Expedition freight office, Trøndelag. The assistant remains genuinely helpful; profanity is the *voice*, not the product.

---

## Eight Traditions

Each tradition is a full personality with its own worldview — not an intensity level or word list.

| Tradition | Register | Swear Mechanism |
|-----------|----------|-----------------|
| `norwegian` *(default)* | Tour guide who's seen it all | Eschatological tourism, wry resignation |
| `british` | Dept. head writing a reference | Devastating restraint, implied disappointment |
| `american` | Sports commentator on fire | Density and emphasis, FUCK as punctuation |
| `quebecois` | Lapsed priest who misses the vocabulary | Sacre stacking, sacramental objects |
| `german` | Quality inspector filing a report | Precision compound insults |
| `italian` | Opera singer arguing with the universe | Operatic theatrical grievance |
| `french` | Aristocrat who's had enough | Ancestral defamation, genealogical contempt |
| `shakespeare` | Scholar of theatrical contempt | Elizabethan slot construction, canonical quotes |

**Surprise Me** — context-aware auto-selection. The bot reads the topic and deploys the appropriate tradition, then announces which one and why.

---

## Discord Commands

```
/hell tradition:[norwegian|british|american|quebecois|german|italian|french|shakespeare|surprise]
/hell reset
/hell who
```

Normal chat in the designated channel is handled automatically. Embed footer shows active tradition and heat level.

Heat level (1–5) is emergent — the model tracks user frustration and escalates accordingly. Users cannot set it directly.

---

## LLM Backend

Uses an Ollama Cloud endpoint (Nemotron) via the OpenAI-compatible API. Local fallback on Qwen 30B. Configuration lives in `bot/hellgpt.ini`; credentials are read from environment variables — never stored in config files.

```ini
[llm]
provider = ollama_cloud
model = nemotron-3-nano:30b-cloud
api_key_env = OLLAMA_API_KEY
```

---

## Personality System

Loaded from numbered instruction files in `instructions/`:

```
01-identity.md          Base character, voice, heat level system
02-response-format.md   Discord formatting, profanity placement rules
03-downtime.md          Error/downtime response templates
traditions/             Per-tradition overlays (injected at session start)
```

Example conversations in `data/examples/` are the most important data files — the model learns register from examples, not from rules or lexicons.

---

## Setup

```bash
cp .env.example .env
# Fill in HELLGPT_DISCORD_TOKEN and OLLAMA_API_KEY
pip install -r requirements.txt
python bot/hellgpt.py
```

---

## Deployment

```bash
./deploy.sh                              # default: tommyl@100.96.31.44:hellgpt/
./deploy.sh user@host:path               # explicit target
```

Rsyncs files, restarts the screen session, and ensures an `@reboot` crontab entry on the remote. Environment variables are sourced from `~/.bashrc` on the remote host.

---

## Project Structure

```
bot/                    Discord bot + config
data/examples/          Example conversations (most critical — defines register)
data/traditions/        Vocabulary lexicons (YAML)
data/patterns/          Construction pattern files (YAML)
instructions/           System prompt files + tradition overlays
logs/                   Runtime logs (gitignored)
```
