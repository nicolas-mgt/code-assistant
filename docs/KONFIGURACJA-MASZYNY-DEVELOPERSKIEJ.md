# Code Assistant — pełna konfiguracja maszyny developerskiej

Stan instrukcji: **14 października 2026 r.** System lokalny: **macOS**. Instrukcja odpowiada konfiguracji wdrożonej w tym repozytorium, z dwoma profilami Zeda, lokalnym Caddy i bramką na k3s.

## 1. Co otrzymasz

Po zakończeniu konfiguracji w natywnym agencie Zeda będą dostępne dwa modele:

| Nazwa widoczna w Zedzie | Provider | Lokalny adres API | Połączenie Caddy z serwerem |
| --- | --- | --- | --- |
| `assistant-network` | `AI Gateway Network` | `http://127.0.0.1:8319` | HTTPS bezpośrednio do `192.168.1.150:443` |
| `assistant-remote` | `AI Gateway Remote` | `http://127.0.0.1:8318` | HTTPS do `home.mmgt.dev:443`, z rozwiązywaniem DNS |

Domyślny jest `assistant-network`. Oba profile używają tego samego konta na serwerze, tego samego klucza naszej bramki i tego samego modelu **GPT-6 Astra**, udostępnionego przez backend pod aliasem **`assistant`**. W Zedzie włączone są **Thinking + High** oraz automatyczne zezwalanie na narzędzia.

Nazwy `assistant-network` i `assistant-remote` są nazwami wyświetlanymi. W żądaniach API oba profile wysyłają `model: assistant`. Różnicę w trasie sieciowej wyznacza lokalny port Caddy, a nie nazwa modelu wysłana do serwera.

```text
Mac developerski                                  Serwer 192.168.1.150

Zed Agent / assistant-network
  └─ http://127.0.0.1:8319 ── Caddy ── HTTPS LAN ──┐
                                                 │
Zed Agent / assistant-remote                      ├─ Traefik /ca/…
  └─ http://127.0.0.1:8318 ── Caddy ── HTTPS DNS ──┘    └─ request-guard → CLIProxyAPI
                                                            ├─ OpenAI / ChatGPT
                                                            └─ OAuth na PVC
```

Pliki projektu, terminal, narzędzia programistyczne i wykonywanie poleceń pozostają na Macu. Treść potrzebna modelowi, np. prompt i odczytane fragmenty plików, jest przesyłana przez bramkę do dostawcy. Przeglądarka logowania, sesja ChatGPT i tokeny OAuth znajdują się na serwerze.

Serwerowy `request-guard` skraca wyłącznie tekstowe wyniki narzędzi przekraczające 10 MiB: zachowuje po 128 KiB początku i końca oraz dodaje informację o pominiętej części. Dotyczy to `function_call_output.output` w Responses oraz treści wiadomości `tool` w Chat Completions. Historia zapisana w Zedzie pozostaje bez zmian. Filtr działa jako dodatkowy kontener w podzie bramki, z tego samego obrazu; jego kompilacja i testy odbywają się podczas budowania obrazu Dockerem.

Na Macu **nie trzeba instalować aplikacji ChatGPT ani lokalnego procesu Codex**. W Zedzie korzystamy z **Zed Agent**, nie z zewnętrznego agenta o nazwie Codex.

## 2. Wybierz właściwą ścieżkę

### A. Nowy Mac, istniejąca i działająca bramka

To standardowy scenariusz. Wykonaj rozdziały **3–10**. Nie musisz budować obrazów, ponownie wdrażać serwera ani ponownie logować konta ChatGPT.

Do pracy klienta wystarczą Zed i Caddy. Python, Make, Git i dostęp SSH są potrzebne do poleceń pomocniczych, pobrania klucza i testów opisanych w instrukcji. Docker nie jest potrzebny do codziennego używania integracji.

### B. Nowy Mac ma także zarządzać bramką

Oprócz rozdziałów 3–10 wykonaj **rozdział 11**, dotyczący lokalnego Dockera, publikacji obrazów i deploymentu. **Rozdział 12** opisuje logowanie lub ponowne logowanie konta wyłącznie na serwerze.

Jeżeli bramka nie została jeszcze wdrożona, kolejność jest następująca:

1. Zależności i repozytorium — rozdziały 3–4.
2. SSH — rozdział 5.
3. Build, push, bootstrap i deploy — rozdział 11.
4. Logowanie i wybór modelu — rozdział 12.
5. Caddy, Zed, klucze i testy — rozdziały 6–10.

Instrukcja zakłada istniejący serwer z k3s, Traefikiem, cert-managerem, `letsencrypt-prod` i StorageClass `local-path`. Nie instaluje od zera systemu serwera ani klastra Kubernetes.

## 3. Zainstaluj zależności na Macu

Wszystkie polecenia bez oznaczenia „na serwerze” wykonuj w lokalnym Terminalu. Przykłady są przeznaczone do standardowej powłoki macOS, czyli zsh.

### 3.1. Narzędzia Apple

Sprawdź, czy są dostępne:

```sh
git --version
make --version
```

Jeżeli system prosi o instalację narzędzi developerskich albo polecenia nie działają:

```sh
xcode-select --install
```

Zakończ instalację w oknie macOS przed kolejnymi krokami. Pełny Xcode nie jest potrzebny do tego projektu.

### 3.2. Homebrew

Sprawdź:

```sh
brew --version
```

Jeżeli Homebrew nie jest zainstalowane, użyj instalatora z [oficjalnej instrukcji Homebrew](https://docs.brew.sh/Installation):

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Wykonaj również polecenia „Next steps” wyświetlone przez instalator. Dodają Homebrew do `PATH`; ścieżka zależy od architektury Maca. Otwórz nowy Terminal i ponownie sprawdź `brew --version`.

### 3.3. Caddy, Python, GitHub CLI i Zed

```sh
brew install caddy python gh
brew install --cask zed
```

Jeżeli będziesz używać hasła SSH z `.env.ssh`, doinstaluj:

```sh
brew install sshpass
```

Przy działającym uwierzytelnianiu SSH kluczem `sshpass` nie jest potrzebny. Zależności potwierdzają oficjalne katalogi: [Caddy](https://formulae.brew.sh/formula/caddy), [Zed](https://formulae.brew.sh/cask/zed), [sshpass](https://formulae.brew.sh/formula/sshpass).

Sprawdź instalację:

```sh
caddy version
python3 --version
gh --version
ssh -V
make --version
```

Skrypty używają wyłącznie biblioteki standardowej Pythona. Nie instalujesz pakietów przez `pip`, nie tworzysz virtualenv i nie uruchamiasz `npm install`. Python powinien mieć wersję co najmniej 3.9.

W konfiguracji referencyjnej przetestowano Caddy 2.11.7 i Zed 1.23.3. Instalacja Homebrew może dostarczyć nowsze wersje; po instalacji wykonaj opisane dalej testy.

## 4. Pobierz prywatne repozytorium

Zaloguj GitHub CLI kontem mającym dostęp do `nicolas-mgt/code-assistant`:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth status
gh auth setup-git
```

To logowanie do **GitHub**, nie do ChatGPT. Może odbywać się w lokalnej przeglądarce. Zasada logowania wyłącznie na serwerze dotyczy konta OpenAI/ChatGPT tej integracji.

Pobierz repozytorium:

```sh
mkdir -p ~/Documents/Projekty
cd ~/Documents/Projekty
gh repo clone nicolas-mgt/code-assistant
cd code-assistant
git status --short
```

Jeżeli repozytorium już istnieje, wejdź do niego i sprawdź lokalne zmiany przed aktualizacją:

```sh
cd ~/Documents/Projekty/code-assistant
git status --short
git pull --ff-only
```

Nie klonuj drugi raz do istniejącego katalogu i nie używaj `git reset --hard` do rozwiązywania problemów z lokalnymi zmianami.

Dalsze polecenia `make ...` wykonuj z katalogu głównego repozytorium. Jeśli wybrałeś inną lokalizację, dostosuj polecenia `cd`.

Najważniejsze pliki:

| Plik | Do czego służy |
| --- | --- |
| [Makefile](../Makefile) | Wszystkie polecenia obsługowe |
| [client/Caddyfile](../client/Caddyfile) | Dwa lokalne wejścia i skrócone ścieżki HTTP |
| [scripts/manage.py](../scripts/manage.py) | Polecenia wykonywane z maszyny developerskiej |
| [scripts/remote.py](../scripts/remote.py) | Operacje uruchamiane na serwerze przez SSH |
| [config/gateway.json](../config/gateway.json) | Szablon konfiguracji serwerowej, bez klucza |
| [k8s/gateway.json](../k8s/gateway.json) | Deployment, Service, TLS i routing |
| [k8s/login.json](../k8s/login.json) | Tymczasowa przeglądarka logowania |
| `.env.ssh` | Lokalny, nieśledzony plik dostępu SSH |
| `.state/images.json` | Nieśledzone referencje obrazów potrzebne do deploy/login |

## 5. Skonfiguruj dostęp SSH do serwera

Serwer w aktualnej sieci lokalnej ma adres `192.168.1.150`, a użyte konto SSH to `mmgt`.

### 5.1. Sprawdź połączenie

```sh
ssh mmgt@192.168.1.150
```

Przy pierwszym połączeniu zweryfikuj fingerprint klucza hosta z zaufanym źródłem. Po zalogowaniu możesz wykonać:

```sh
hostname
uname -m
kubectl get nodes
```

Serwer jest platformą `x86_64`, a obrazy dla niego budujemy jako `linux/amd64`. Zakończ tę sesję poleceniem `exit`.

### 5.2. Utwórz `.env.ssh`

Plik jest czytany przez skrypty, ale **nie jest wykonywany jako skrypt powłoki**. Obsługiwane nazwy pól to dokładnie `CONN` i opcjonalne `PASS`.

Przy uwierzytelnianiu kluczem zawartość może wyglądać tak:

```dotenv
CONN='ssh mmgt@192.168.1.150'
```

Klucz musi już działać, np. przez agenta SSH lub wpis w `~/.ssh/config`. Możesz również podać opcję `-i` w `CONN` z bezwzględną ścieżką do klucza. Skrypt nie rozwija samodzielnie `~` w argumentach tej wartości.

W użytej tutaj konfiguracji dostępne było hasło SSH. Żeby utworzyć plik bez wpisywania hasła do historii terminala, wykonaj poniższy kod z głównego katalogu repozytorium:

```sh
python3 - <<'PY'
import getpass
import os
import shlex

password = getpass.getpass('Hasło SSH (Enter, jeśli używasz klucza): ')
lines = ["CONN=" + shlex.quote('ssh mmgt@192.168.1.150')]
if password:
    lines.append('PASS=' + shlex.quote(password))
fd = os.open('.env.ssh', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('\n'.join(lines) + '\n')
print('Utworzono .env.ssh z uprawnieniami 600')
PY
```

Kod odmówi nadpisania istniejącego pliku. Jeśli `.env.ssh` już istnieje, edytuj go świadomie w edytorze i ustaw uprawnienia:

```sh
chmod 600 .env.ssh
git check-ignore .env.ssh
```

Ostatnie polecenie powinno wypisać `.env.ssh`. Nie publikuj tego pliku ani jego zawartości. Hasło `PASS` jest hasłem serwera SSH, a nie konta ChatGPT.

Skrypty zapisują własną listę znanych hostów w `.state/known_hosts`. Używają `StrictHostKeyChecking=accept-new`: akceptują nowy host, ale odrzucają zmianę wcześniej zapamiętanego klucza.

### 5.3. Sprawdź bramkę

Dla już wdrożonego serwera:

```sh
make status
make models
```

Oczekiwany rezultat to działający pod `ai-gateway`, PVC `Bound`, certyfikat `Ready` i niepusty katalog modeli. Po konfiguracji modelu powinien występować alias `assistant`.

`make status`, `make models`, `make key-copy`, `make zed-config`, `make smoke`, `make login` i deployment wymagają SSH. Samo używanie Zeda po wcześniejszym zapisaniu kluczy nie wymaga aktywnego SSH.

**Poza domem:** profil `assistant-remote` może działać przez domenę, mimo że `make status` lub `make smoke` nie działa — te polecenia nadal potrzebują SSH z `.env.ssh`, które w tej konfiguracji wskazuje prywatny adres LAN. Dostęp administracyjny spoza LAN wymaga osobno dostępnej trasy SSH, np. VPN. Nie zmieniamy w tej instrukcji ekspozycji SSH na internet.

## 6. Sprawdź i uruchom lokalny Caddy

### 6.1. Walidacja

```sh
make check
```

Polecenie waliduje Caddyfile i uruchamia sześć testów: mapowania, przenoszenie metody/body/query/autoryzacji, błędy backendu, streaming z anulowaniem, odrzucanie obcych tras, konfigurację LAN/TLS oraz zgodność tras Traefika w ramach tych przypadków testowych.

Nie wymaga zalogowanego ChatGPT ani dostępu SSH. Wymaga działającego lokalnego Caddy w `PATH` i możliwości otwarcia tymczasowych portów loopback. Końcowy wynik powinien zawierać `OK`.

### 6.2. Start

W osobnej karcie Terminala:

```sh
cd ~/Documents/Projekty/code-assistant
make client
```

Pozostaw tę kartę otwartą. Jeden proces Caddy obsługuje oba porty:

- `127.0.0.1:8319` — Network;
- `127.0.0.1:8318` — Remote.

Caddy działa na pierwszym planie. `Ctrl+C` zatrzymuje oba profile. Nie skonfigurowaliśmy autostartu przez launchd ani `brew services`. Samo `brew services start caddy` użyłoby konfiguracji usługi Homebrew, a nie automatycznie naszego pliku z repozytorium.

Nasza konfiguracja wyłącza panel administracyjny Caddy. Po zmianie `client/Caddyfile` zatrzymaj proces i uruchom `make client` ponownie; nie zakładaj, że `caddy reload` zadziała przy wyłączonym API administracyjnym.

### 6.3. Co dokładnie robi Caddy

| Metoda | Lokalny URL w obu profilach | URL wysłany do Traefika | Ścieżka backendu |
| --- | --- | --- | --- |
| GET | `/models` | `/ca/m` | `/v1/models` |
| POST | `/chat/completions` | `/ca/c/c` | `/v1/chat/completions` |
| POST | `/responses` | `/ca/r` | `/v1/responses` |

Inne ścieżki i metody zwracają 404. Caddy zachowuje nagłówek `Authorization` wysłany przez Zeda. Klucz nie jest zapisany w Caddyfile. Parametry zapytania, body i streaming są przekazywane dalej.

W profilu Network cel połączenia TCP jest stały: `192.168.1.150:443`. Caddy wysyła jednocześnie:

- nagłówek HTTP `Host: home.mmgt.dev`, żeby dopasować istniejącą trasę Traefika;
- nazwę TLS/SNI `home.mmgt.dev`, żeby poprawnie zweryfikować certyfikat.

Nazwa domeny w nagłówku i SNI **nie oznacza połączenia przez jej publiczny adres IP**. Transport Network łączy się bezpośrednio z adresem LAN. Nie trzeba modyfikować `/etc/hosts` ani wyłączać sprawdzania certyfikatu. Takie użycie `tls_server_name` opisuje [dokumentacja Caddy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#the-http-transport).

HTTP występuje wyłącznie na lokalnym loopback pomiędzy Zedem a Caddy. Połączenie z Maca do serwera jest HTTPS w obu profilach.

### 6.4. Szybkie sprawdzenie bez klucza

W drugiej karcie Terminala:

```sh
curl -i http://127.0.0.1:8319/models
curl -i http://127.0.0.1:8318/models
```

Oczekiwany wynik to **401 Unauthorized**, ponieważ te żądania nie zawierają klucza. To poprawny wynik: potwierdza, że lokalny proxy dotarł do chronionej bramki.

## 7. Skonfiguruj dwa profile w Zedzie

### 7.1. Zrób kopię ustawień

Ustawienia użytkownika znajdują się w `~/.config/zed/settings.json`. Zed dopuszcza tam komentarze i końcowe przecinki, czyli składnię JSONC.

Po pierwszym uruchomieniu Zeda, jeśli plik już istnieje:

```sh
cp -p ~/.config/zed/settings.json ~/.config/zed/settings.json.before-ai-gateway-$(date +%Y%m%d-%H%M%S)
```

W Zedzie otwórz paletę poleceń `Cmd+Shift+P`, a następnie wybierz `zed: open settings file`.

### 7.2. Wygeneruj aktualny fragment konfiguracji

Z katalogu repozytorium:

```sh
make zed-config
```

Wynik zawiera dwa providery oraz domyślny model z włączonym Thinking i poziomem High. Polecenie **tylko wypisuje JSON**. Nie edytuje samodzielnie ustawień Zeda i nie instaluje kluczy.

Jeśli pojawi się informacja o konieczności wykonania `make configure`, serwer nie ma jeszcze metadanych wybranego modelu — przejdź do rozdziału 12. Nie wykonuj konfiguracji serwera ponownie tylko po to, aby dodać kolejnego Maca, jeśli poprzednia konfiguracja już działa.

### 7.3. Kompletny fragment referencyjny

Poniższy JSON jest kompletną konfiguracją integracji dla używanej Astry, z full auto. Można go użyć jako całego pliku tylko przy świeżych ustawieniach. W istniejącym pliku **scal sekcje** `language_models` i `agent`, zachowując motyw, skróty, inne providery i pozostałe ustawienia. Nie twórz dwóch oddzielnych kluczy `agent` na tym samym poziomie.

```json
{
  "language_models": {
    "openai_compatible": {
      "AI Gateway Network": {
        "api_url": "http://127.0.0.1:8319",
        "available_models": [
          {
            "name": "assistant",
            "display_name": "assistant-network",
            "max_tokens": 1050000,
            "max_output_tokens": 128000,
            "reasoning_effort": "high",
            "capabilities": {
              "tools": true,
              "images": true,
              "parallel_tool_calls": true,
              "prompt_cache_key": false,
              "chat_completions": false
            }
          }
        ]
      },
      "AI Gateway Remote": {
        "api_url": "http://127.0.0.1:8318",
        "available_models": [
          {
            "name": "assistant",
            "display_name": "assistant-remote",
            "max_tokens": 1050000,
            "max_output_tokens": 128000,
            "reasoning_effort": "high",
            "capabilities": {
              "tools": true,
              "images": true,
              "parallel_tool_calls": true,
              "prompt_cache_key": false,
              "chat_completions": false
            }
          }
        ]
      }
    }
  },
  "agent": {
    "default_model": {
      "provider": "AI Gateway Network",
      "model": "assistant",
      "enable_thinking": true,
      "effort": "high"
    },
    "tool_permissions": {
      "default": "allow"
    },
    "sandbox_permissions": {
      "allow_unsandboxed": true
    },
    "expand_terminal_card": false,
    "expand_edit_card": false,
    "thinking_display": "always_collapsed"
  }
}
```

Nie dodawaj `/v1`, `/ca`, `/responses` ani `/models` do `api_url`. Zed sam dopisuje standardową ścieżkę, a Caddy mapuje ją na skrót publiczny.

### 7.4. Znaczenie ważnych pól

| Ustawienie | Znaczenie |
| --- | --- |
| `name: assistant` | Alias wymagany przez nasz backend |
| `display_name` | Etykieta widoczna w selektorze modelu Zeda |
| `chat_completions: false` | Zed używa Responses API dla tego modelu |
| `tools: true` | Włączona obsługa narzędzi agenta |
| `parallel_tool_calls: true` | Dopuszczone równoległe wywołania narzędzi |
| `images: true` | Włączone dodawanie obrazów do wiadomości agenta |
| `prompt_cache_key: false` | Wymagane pole struktury możliwości; bez niego użyta wersja Zeda zgłaszała błąd ustawień |
| `reasoning_effort: high` | Domyślny poziom modelu i udostępnienie sterowania Thinking w Zedzie |
| `enable_thinking: true` | Włączenie Thinking w domyślnym wyborze agenta |
| `effort: high` | Poziom wybrany dla domyślnego agenta |
| `thinking_display: always_collapsed` | Tylko sposób pokazywania bloków myślenia; nie wyłącza reasoning |

Limity 1 050 000 kontekstu i 128 000 wyjścia wpisano dla wybranego modelu na podstawie [specyfikacji GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra). Nie są gwarancją, że każde konto lub pośrednik dopuści żądanie o maksymalnym rozmiarze. Przy zmianie modelu trzeba zweryfikować jego parametry.

### 7.5. Thinking: potrzebne są oba ustawienia

Samo `reasoning_effort: high` w `available_models` nie wystarcza. Jeżeli Thinking jest wyłączone w rozmowie, provider Zeda może wysłać `reasoning.effort: none`. Astra odrzuca tę wartość. Po poprawce opisanej poniżej bramka zamienia ją na `low`, ale nie zapewnia to oczekiwanego High w rozmowie.

Dlatego konfiguracja zawiera także `enable_thinking: true` i `effort: high` w `agent.default_model`.

W już otwartej rozmowie sprawdź dolny pasek:

1. Włącz ikonę **Thinking**.
2. Wybierz poziom **High**.
3. Wybierz właściwy profil Network albo Remote.

Istniejące rozmowy mogą zachowywać własny wybór Thinking/modelu mimo zmiany ustawień domyślnych. Nowa rozmowa powinna od razu pokazywać High. Ta różnica spowodowała błąd `none` podczas pierwszej konfiguracji i została uwzględniona powyżej.

**Automatyczne tytuły rozmów:** Zed 1.23.3 wysyła osobne żądanie tytułu z wyłączonym Thinking, niezależnie od High w rozmowie. Dlatego w `config/gateway.json` jest warunkowa reguła `requests.payload.override`: wyłącznie dla `gpt-6-astra` zamienia `reasoning.effort: none` na `low`. Zachowuje jawnie wybrane `high`, `xhigh` i pozostałe wartości. Dotyczy każdego żądania Astry z `none`, nie tylko tytułów. Nie trzeba dodawać drugiego modelu ani ustawiać `agent.thread_summary_model`.

Nowy bootstrap zapisuje tę regułę z szablonu. Na istniejącym serwerze aktualizuje ją `make configure MODEL=gpt-6-astra CONTEXT=1050000 OUTPUT=128000`; sam `make deploy` nie aktualizuje zawartości istniejącego sekretu konfiguracji. Reguła działa dla Network i Remote, bez zmian na pozostałych Macach.

### 7.6. Full auto

Ustawienia `tool_permissions.default: allow` i `sandbox_permissions.allow_unsandboxed: true` odtwarzają uzgodniony tryb pracy: narzędzia mają domyślną zgodę, a terminal agenta działa poza sandboxem Zeda z uprawnieniami użytkownika macOS.

Jest to ustawienie **globalne użytkownika Zeda**, nie ograniczone do providera Network lub Remote. Dodatkowe reguły projektu/profilu, np. jawne `always_confirm` lub `always_deny`, mogą nadal wpływać na zgodę. Uprawnień systemowych macOS, takich jak zgoda na dostęp do chronionych katalogów, to ustawienie nie zastępuje.

Panel `Edits`, przyciski `Keep All` i `Reject All` mogą pozostać widoczne. Służą do przeglądu już zastosowanych zmian; ich obecność sama w sobie nie oznacza, że agent czeka na zgodę na kolejne narzędzie.

`make zed-config` generuje ustawienia providerów i domyślnego modelu. **Nie generuje ustawień full auto** — dodaj powyższe sekcje ręcznie, jeśli chcesz odtworzyć także ten tryb.

## 8. Zapisz klucz bramki w obu providerach Zeda

### 8.1. Jaki to klucz

To osobny klucz dostępu do naszej bramki. Nie jest kluczem API OpenAI ani tokenem OAuth ChatGPT. Powstał na serwerze podczas bootstrapu i jest przechowywany w `Secret/ai-gateway-config`.

Zed przechowuje lokalną kopię tego klucza przez systemowy mechanizm poświadczeń. **Nie wpisuj go do `settings.json`, Caddyfile, poleceń `curl -H ...` w historii ani do Git.**

Oba providery używają tej samej wartości klucza, ale mają różne adresy API. Skonfiguruj poświadczenia dla każdego osobno.

### 8.2. Network

1. W lokalnym Terminalu, w repozytorium, wykonaj:

   ```sh
   make key-copy
   ```

2. Polecenie pobierze klucz przez SSH i umieści go w schowku przez `pbcopy`. Nie wypisuje wartości na ekran.
3. W Zedzie otwórz `Cmd+Shift+P` → `agent: open settings`.
4. Wejdź w **AI → LLM Providers → Configure**.
5. Przy **AI Gateway Network** wybierz **Configure**.
6. Wklej klucz w pole API key i zatwierdź Enterem.
7. Sprawdź potwierdzenie **API key configured for http://127.0.0.1:8319**.
8. Jeśli macOS wyświetli monit pęku kluczy, zatwierdź dostęp Zeda do tego poświadczenia w systemowym oknie. Nie wpisuj hasła macOS w czacie.

### 8.3. Remote

Wykonaj ponownie `make key-copy` i powtórz kroki dla **AI Gateway Remote**. Potwierdzenie powinno dotyczyć `http://127.0.0.1:8318`.

Po zapisaniu obu kluczy wyczyść schowek:

```sh
printf '' | pbcopy
```

Jeżeli klucz był wcześniej zapisany dla starego providera `AI Gateway`, po utworzeniu nowych providerów nadal sprawdź ich własne ekrany konfiguracji. Nie zakładaj, że zmiana nazwy automatycznie załatwi uwierzytelnienie w działającej sesji Zeda.

## 9. Uruchom właściwego agenta i wybierz trasę

1. Otwórz katalog projektu w Zedzie.
2. W panelu agentów użyj menu nowej rozmowy, np. przycisku `+`.
3. Wybierz **Zed Agent**.
4. W selektorze modelu wybierz `assistant-network` albo `assistant-remote`.
5. Sprawdź, że Thinking jest włączone, a poziom to **High**.
6. Do edycji plików używaj profilu pracy **Write**.

Nie wybieraj pozycji **Codex**, **Claude Agent** ani **Cursor** z listy External Agents, jeśli chcesz korzystać z opisywanej integracji. Istniejące konfiguracje tych narzędzi mogą pozostać w Zedzie, ale są niezależne od naszej bramki.

### Kiedy używać którego profilu

- **W domowej sieci:** `assistant-network`; pakiety idą bezpośrednio do IP serwera w LAN.
- **Poza domową siecią:** `assistant-remote`; potrzebna jest dostępność domeny i HTTPS serwera.
- **Przez VPN zapewniający trasę do LAN:** Network może również działać, jeśli `192.168.1.150` jest osiągalne.

Nie ma automatycznego przełączenia Network → Remote ani przełączenia na bezpośrednie API OpenAI. Jeśli wybrana trasa nie działa, zobaczysz błąd i możesz ręcznie wybrać drugi profil.

Oba profile nadal prowadzą do tej samej bramki. Zmiana profilu nie tworzy nowego konta, nie rozdziela limitów konta i nie zmienia faktycznego modelu serwerowego.

## 10. Sprawdź całość

### 10.1. Test bramki przez oba wejścia

Caddy powinien działać w osobnej karcie Terminala. W drugiej karcie:

```sh
make smoke SMOKE_URL=http://127.0.0.1:8319
make smoke SMOKE_URL=http://127.0.0.1:8318
```

Oczekiwany komunikat dla każdego profilu:

```text
Authentication, catalog and streamed generation passed
```

Test sprawdza odmowę dla braku klucza i błędnego klucza, obecność aliasu `assistant` oraz rzeczywiste zakończone generowanie strumieniowe. Wysyła krótkie żądanie do modelu, więc korzysta z limitów zalogowanego konta.

Samo `make smoke` bez zmiennych testuje **port 8318, czyli Remote**. Domyślny profil Zeda jest Network, ale domyślny adres tego skryptu pozostał Remote. Smoke nie wymusza reasoning High; sprawdzenie tego ustawienia wykonujemy także w samym Zedzie.

Opcjonalnie sprawdź bezpośrednio publiczne skrócone endpointy:

```sh
make smoke SMOKE_URL=https://home.mmgt.dev/ca
```

Pamiętaj, że nawet test publicznego adresu pobiera klucz przez SSH, więc jego dostępność nadal jest wymagana.

### 10.2. Test odpowiedzi w Zedzie

Wybierz `assistant-network` i wyślij:

```text
Test połączenia. Odpowiedz wyłącznie NETWORK_OK. Nie używaj narzędzi.
```

Następnie wybierz `assistant-remote` i wyślij:

```text
Test połączenia. Odpowiedz wyłącznie REMOTE_OK. Nie używaj narzędzi.
```

Po teście wybierz z powrotem Network, jeżeli ma być Twoim domyślnym profilem. Sprawdź też `agent.default_model`, jeśli świadomie zmieniasz domyślny wybór.

### 10.3. Test lokalnych plików i terminala

Utwórz osobny katalog testowy, nie nadpisując wcześniejszych testów:

```sh
mkdir -p .state
CA_SMOKE_DIR=$(mktemp -d "$PWD/.state/agent-smoke.XXXXXX")
printf 'def add(a, b):\n    return a - b\n' > "$CA_SMOKE_DIR/calculator.py"
/Applications/Zed.app/Contents/MacOS/cli --new "$CA_SMOKE_DIR"
```

W nowym oknie wybierz Zed Agent i właściwy profil, a następnie wyślij:

```text
Pracuj wyłącznie w otwartym katalogu testowym. Odczytaj calculator.py
lokalnym narzędziem. Popraw funkcję add, aby dodawała argumenty, i zapisz
plik. Uruchom w lokalnym terminalu:
python3 -c "from calculator import add; assert add(2, 3) == 5; print('AGENT_SMOKE_OK')"
Nie czytaj plików poza tym katalogiem i nie używaj sieci. Podaj wynik.
```

Oczekiwane rezultaty:

1. Agent faktycznie odczytał plik narzędziem.
2. Plik na dysku zawiera `return a + b`.
3. Polecenie zostało wykonane lokalnie i wypisało `AGENT_SMOKE_OK`.
4. Przy skonfigurowanym full auto nie pojawiło się żądanie zgody na terminal.

Katalog `.state` jest ignorowany przez Git. Nie wysyłaj jako kontekstu `.env.ssh` ani plików poświadczeń.

### 10.4. Test przerwania

Poproś model o dłuższą odpowiedź, np. wypisywanie kolejnych liczb, i użyj przycisku Stop podczas streamingu. Odpowiedź powinna się zatrzymać. Test automatyczny sprawdza anulowanie na atrapowym backendzie; podczas pierwotnego wdrożenia potwierdziliśmy również zamknięcie rzeczywistego połączenia z ChatGPT po zatrzymaniu odpowiedzi w Zedzie.

### 10.5. Co zostało sprawdzone przy przygotowaniu tej konfiguracji

- TLS i autoryzacja bramki.
- Sześć testów automatycznych obecnej konfiguracji Caddy i manifestów.
- Rzeczywiste generowanie w Zedzie przez Network i Remote.
- Odczyt, edycja pliku i wykonanie lokalnego polecenia.
- Full auto bez potwierdzenia lokalnego terminala.
- Thinking High w nowej rozmowie bez błędu `none`.
- Zachowanie logowania po odtworzeniu poda bramki.
- Anulowanie streamingu i zamknięcie połączenia do ChatGPT.
- Widoczny błąd przy zatrzymanej bramce i poprawne działanie po jej przywróceniu.
- Połączenie do ChatGPT z poda serwera podczas generowania.
- Działanie istniejących endpointów `/livez` i `/readyz` po wdrożeniu.

To zapis wykonanej weryfikacji, nie zastępstwo testów na nowym komputerze. Nie instalowaliśmy globalnej blokady ruchu do OpenAI na macOS.

## 11. Opcjonalnie: build i deployment z maszyny developerskiej

Ten rozdział jest potrzebny tylko wtedy, gdy ten Mac ma publikować obrazy lub zarządzać wdrożeniem. Zwykły użytkownik istniejącej bramki może go pominąć.

### 11.1. Docker lokalnie

Podczas konfiguracji korzystaliśmy z OrbStack. Jeśli masz już działający Docker Desktop lub inny zgodny lokalny silnik Dockera z Buildx, użyj go.

Instalacja OrbStack:

```sh
brew install --cask orbstack
open -a OrbStack
```

Zakończ konfigurację aplikacji, zgodnie z [instrukcją pakietu](https://formulae.brew.sh/cask/orbstack), i sprawdź:

```sh
docker version
docker info
docker buildx version
```

`docker version` powinno pokazywać działający serwer Dockera, nie tylko klienta. Na Macu Apple Silicon budowa nadal musi dotyczyć `linux/amd64`; `make build` ustawia tę platformę jawnie.

### 11.2. Uwierzytelnianie do prywatnego GHCR

Repozytorium i obrazy są prywatne:

- `ghcr.io/nicolas-mgt/code-assistant`;
- `ghcr.io/nicolas-mgt/code-assistant-login`.

GHCR to rejestr GitHub, nie usługa uruchomiona na `192.168.1.150`. Lokalnie budujemy obrazy Dockerem i wysyłamy je do GHCR. **Nie używamy GitHub Actions.**

Do publikacji potrzebujesz uprawnień do pakietów, w praktyce odpowiedniego tokenu klasycznego z `write:packages`. Dostęp do prywatnego repozytorium i dostęp do prywatnych pakietów sprawdzaj osobno. Serwerowi do pobierania wystarcza odpowiednio uprawniony token `read:packages`. Szczegóły: [uwierzytelnianie GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Logowanie bez wpisywania tokenu do historii i argumentów procesu:

```sh
python3 - <<'PY'
import getpass
import subprocess

token = getpass.getpass('Token GitHub do publikacji w GHCR: ')
subprocess.run(
    ['docker', 'login', 'ghcr.io', '-u', 'nicolas-mgt', '--password-stdin'],
    input=token + '\n', text=True, check=True,
)
PY
```

To przykład dla konta `nicolas-mgt`; przy innym uprawnionym koncie zmień login. Docker może zapisać poświadczenie przez swój skonfigurowany credential helper. Nie kopiuj tokenu do Dockerfile ani manifestów.

### 11.3. Zbuduj i opublikuj

```sh
git status --short
make check
make build
make push
```

`make build` wymaga czystego drzewa Git, ponieważ obrazy otrzymują tag pełnego identyfikatora commita. Jeśli zmieniałeś pliki, najpierw je przejrzyj i zatwierdź świadomie w Git; nie usuwaj zmian tylko po to, aby przejść ten warunek.

Obrazy są budowane lokalnie z baz przypiętych digestami, oznaczone etykietą źródłowego repozytorium i rewizji. `make push` zapisuje referencje z digestami w `.state/images.json`. Nie wdrażamy pływającego tagu `latest`.

Kontekst budowania jest ograniczony przez `.dockerignore` do katalogu `docker/`. `.env.ssh`, `.state`, ustawienia Zeda i tokeny nie trafiają do obrazu.

### 11.4. Sprawdź warunki na istniejącym k3s

Przykładowe polecenia przez SSH:

```sh
ssh mmgt@192.168.1.150 'kubectl get nodes'
ssh mmgt@192.168.1.150 'kubectl get storageclass local-path'
ssh mmgt@192.168.1.150 'kubectl get clusterissuer letsencrypt-prod'
ssh mmgt@192.168.1.150 'kubectl get crd ingressroutes.traefik.io middlewares.traefik.io certificates.cert-manager.io'
```

Konto SSH musi mieć działający `kubectl` i dostęp do zasobów niezbędnych do wdrożenia. Polecenia w skryptach nie poprzedzają `kubectl` przez `sudo`.

### 11.5. Bootstrap

Podczas pierwszego wdrożenia skopiowaliśmy na serwerze istniejący sekret dostępu do GHCR z `smart-home/ghcr-smart-home`:

```sh
make bootstrap PULL_SECRET_SOURCE=smart-home/ghcr-smart-home
```

To konkretne źródło z obecnego serwera, a nie uniwersalna nazwa sekretu. Jeśli nie istnieje lub nie ma dostępu do naszych pakietów, administrator musi przygotować poprawny sekret typu `kubernetes.io/dockerconfigjson` i wskazać go jako `namespace/nazwa`.

Obecna implementacja `make bootstrap` **kopiuje istniejący sekret serwerowy**; nie przyjmuje tokenu GHCR jako lokalnego argumentu i nie tworzy źródłowego sekretu od zera. Nie trzeba przenosić zawartości tego sekretu na Maca. Uprawnienia skopiowanego tokenu pozostają takie, jakie miał token źródłowy — samo kopiowanie nie ogranicza ich do `read:packages`.

Bootstrap tworzy namespace `ai-gateway`, PVC `ai-gateway-auth`, sekret `ghcr-pull` i konfigurację bramki z kluczem wygenerowanym na serwerze. Istniejących kluczy i PVC nie resetuje. Gdy `ghcr-pull` już istnieje, kolejne wywołanie nie wymaga ponownego wskazywania źródła:

```sh
make bootstrap
```

### 11.6. Deployment

```sh
make deploy
make status
```

`make deploy` czyta `.state/images.json`, wykonuje walidację manifestu przez serwer Kubernetes, stosuje konfigurację i czeka na rollout oraz certyfikat.

Powstają m.in. jedna replika bramki, Service ClusterIP na 8317, certyfikat `home.mmgt.dev` w nowym namespace i trzy dokładne trasy `/ca/...`. Management API i panel logowania nie mają publicznego routingu.

Po pierwszym wdrożeniu wykonaj rozdział 12. Po zwykłej aktualizacji obrazu nie trzeba ponownie logować konta, o ile jego zapisane tokeny są nadal ważne.

### 11.7. Aktualizacje i powrót do wcześniejszego obrazu

Zapisz poprzednie referencje przed kolejną publikacją:

```sh
cp .state/images.json .state/images-before-update.json
make build
make push
make deploy
make smoke SMOKE_URL=http://127.0.0.1:8319
```

Powyższa sekwencja zakłada wcześniej zatwierdzone zmiany i działający Caddy do smoke testu. Aby wrócić do zapisanych digestów:

```sh
cp .state/images-before-update.json .state/images.json
make deploy
```

Deployment zachowuje PVC i sekrety. Nie usuwaj namespace ani PVC w ramach zwykłej aktualizacji lub ponownego logowania.

Zmiana wyłącznie lokalnego Caddy, skryptów obsługowych lub ustawień Zeda nie wymaga przebudowy obrazów serwera. Zmiana Caddy wymaga lokalnego restartu `make client`.

## 12. Opcjonalnie: logowanie ChatGPT wyłącznie na serwerze

### 12.1. Kiedy jest potrzebne

Logowanie wykonaj przy pierwszym wdrożeniu albo gdy zapisane konto wymaga ponownego uwierzytelnienia. Dodanie kolejnego Maca nie wymaga nowego logowania, jeśli serwer już działa.

### 12.2. Przygotuj `.state/images.json`

`make login` potrzebuje tego pliku, żeby wiedzieć, który prywatny obraz przeglądarki uruchomić. Plik jest ignorowany przez Git, dlatego **nie pojawia się po świeżym klonowaniu repozytorium**.

Masz trzy możliwości:

1. Wygenerować go przez `make build` i `make push`, jeśli publikujesz nową wersję.
2. Skopiować aktualny `.state/images.json` z zaufanej maszyny administracyjnej. Zawiera referencje obrazów, nie tokeny.
3. Dla dokładnie wdrożonej wersji z dnia tej instrukcji użyć poniższego zapisu.

Trzecia opcja odtwarza referencje obrazów, a nie aktualizuje serwera. Wykonuj ją tylko wtedy, gdy pliku jeszcze nie ma i nadal używasz tego wydania:

```sh
python3 - <<'PY'
import json
from pathlib import Path

Path('.state').mkdir(mode=0o700, exist_ok=True)
images = {
    'GATEWAY_IMAGE': 'ghcr.io/nicolas-mgt/code-assistant@sha256:d6d16997002dd8ac4540a50f3b4f8e2ca6c63028b4d003233a9b6472860eb7ae',
    'LOGIN_IMAGE': 'ghcr.io/nicolas-mgt/code-assistant-login@sha256:7ff7a0bf8c9d8b9dd667b05ba40e018d89efa6a69fdeed6a228f3900015b345e',
}
with Path('.state/images.json').open('x') as output:
    json.dump(images, output, indent=2)
    output.write('\n')
PY
```

Nie nadpisuj tym nowszych digestów po aktualizacji. Samo podanie zmiennych `GATEWAY_IMAGE`/`LOGIN_IMAGE` do `make deploy` nie zastępuje brakującego pliku: skrypt najpierw go odczytuje.

### 12.3. Uruchom sesję

```sh
make login
```

Skrypt:

1. Sprawdza dostępność lokalnego portu 33000.
2. Tworzy tymczasowy pod `ai-login` w namespace `ai-gateway`.
3. Czeka, aż przeglądarka wystartuje; pierwszy start może trwać dłużej z powodu pobrania obrazu.
4. Uruchamia port-forward na loopback serwera i tunel SSH do loopback Maca.
5. Uruchamia w podzie bramki proces logowania urządzenia.
6. Wypisuje adres pulpitu i nowy kod urządzenia.

Pozostaw polecenie uruchomione. Otwórz lokalnie:

```text
http://127.0.0.1:33000/
```

Widzisz zdalny pulpit. **Dopiero wewnątrz widocznego Chromium działającego na serwerze** otwórz:

```text
https://auth.openai.com/codex/device
```

Nazwa dostawcy w tym adresie jest wymagana przez jego proces logowania. Nie jest publiczną nazwą naszej integracji ani ścieżką API używaną przez Zeda.

### 12.4. Zakończ autoryzację urządzenia

1. W zdalnym Chromium zaloguj konto ChatGPT.
2. Wykonaj MFA w tej samej zdalnej przeglądarce.
3. Wpisz aktualny kod urządzenia wyświetlony przez `make login`.
4. Zatwierdź dostęp i poczekaj na końcowe potwierdzenie.
5. Sprawdź wynik polecenia w Terminalu.

**Samo zalogowanie do konta w przeglądarce nie wystarcza.** Proces musi jeszcze otrzymać zatwierdzenie kodu urządzenia. Podczas pierwszej konfiguracji właśnie brak zakończenia tego etapu spowodował timeout.

Kod ma ograniczoną ważność; użyta wersja procesu czeka maksymalnie około 15 minut. Korzystaj zawsze z nowego kodu z bieżącego uruchomienia. Nie kopiuj kodów ze starych wiadomości czy logów.

Oczekiwany komunikat sukcesu:

```text
Authentication completed; tokens are stored on the server
```

Po zakończeniu skrypt zamyka tunel i usuwa pod przeglądarki. Profil Chromium był w pamięci tymczasowego poda. Tokeny bramki pozostają na PVC `/data/auth`.

Jeżeli po sukcesie `http://127.0.0.1:33000/` przestaje działać, jest to oczekiwane. Nie jest to stały panel administracyjny.

### 12.5. Zasady pracy ze zdalnym pulpitem

- Nie otwieraj strony logowania ChatGPT jako osobnej lokalnej karty, jeśli chcesz zachować sesję i cookies wyłącznie na serwerze.
- Schowek zdalnego pulpitu i transfer plików są wyłączone. Kod urządzenia może wymagać ręcznego przepisania.
- Używaj jednego klienta pulpitu naraz; kolejne połączenie może przejąć sesję i rozłączyć poprzednią kartę.
- Nie wpisuj hasła ani kodów MFA do czatu lub plików repozytorium.
- Tymczasowy pod ma dodatkowo limit życia 30 minut. Nie traktuj tego jako przedłużenia ważności kodu logowania.

Po błędzie lub przerwaniu sprawdź, czy pozostał pod. Możesz usunąć wyłącznie tymczasową przeglądarkę:

```sh
make login-stop
```

Zatrzymaj także poprzednie `make login` przez `Ctrl+C`, jeśli nadal działa. Nową próbę uruchom dopiero po zwolnieniu portu 33000. `make login-stop` nie usuwa tokenów z PVC.

### 12.6. Wybierz i zapisz model

Po zalogowaniu:

```sh
make models
```

Sprawdź dostępność konkretnego modelu. Dla wybranego w tej konfiguracji `gpt-6-astra`:

```sh
make configure MODEL=gpt-6-astra CONTEXT=1050000 OUTPUT=128000
```

Polecenie ustawia na serwerze mapowanie `assistant` → `gpt-6-astra`, zapisuje metadane klienta, synchronizuje reguły `requests.payload` z `config/gateway.json` i restartuje Deployment. Nie wybiera automatycznie najnowszego modelu. Zmiana dotyczy **obu profili i wszystkich klientów tej bramki**.

Następnie:

```sh
make models
make zed-config
```

Wróć do rozdziałów 6–10. `make configure` nie edytuje lokalnego pliku ustawień Zeda; zmienione limity czy model trzeba uwzględnić w kliencie.

## 13. Codzienna praca i obsługa

### Start po ponownym uruchomieniu Maca

```sh
cd ~/Documents/Projekty/code-assistant
make client
```

Następnie otwórz projekt w Zedzie i wybierz Zed Agent → `assistant-network` lub `assistant-remote`. Nie musisz uruchamiać Dockera, tunelu logowania, SSH ani aplikacji ChatGPT do samej rozmowy, jeśli klucz jest już zapisany, a serwer działa.

### Tabela poleceń

| Polecenie | Działanie | Wymaga SSH |
| --- | --- | --- |
| `make check` | Walidacja Caddy i testy lokalne | Nie |
| `make client` | Dwa lokalne wejścia Caddy na pierwszym planie | Nie |
| `make key-copy` | Kopiuje klucz bramki do schowka Maca | Tak |
| `make zed-config` | Wypisuje fragment ustawień dwóch providerów | Tak |
| `make models` | Odczytuje katalog z serwera | Tak |
| `make smoke` | Testuje port 8318, w tym prawdziwe generowanie | Tak |
| `make smoke SMOKE_URL=http://127.0.0.1:8319` | Testuje połączenie LAN | Tak |
| `make status` | Zasoby k3s i ostatnie logi bramki | Tak |
| `make login` | Tymczasowa przeglądarka i logowanie na serwerze | Tak |
| `make login-stop` | Usuwa tymczasowy pod przeglądarki | Tak |
| `make configure MODEL=... CONTEXT=... OUTPUT=...` | Zmienia model serwerowy i metadane klienta | Tak |
| `make build` | Buduje oba obrazy lokalnie Dockerem | Nie |
| `make push` | Wysyła obrazy do GHCR i zapisuje ich digesty | Nie |
| `make bootstrap` | Przygotowuje namespace, PVC i sekrety | Tak |
| `make deploy` | Wdraża digest z lokalnego pliku stanu | Tak |

### Co przechowujemy gdzie

| Dane | Miejsce |
| --- | --- |
| Kod projektu i narzędzia developerskie | Mac |
| Klucz naszej bramki | Secret na serwerze i poświadczenia providerów Zeda na Macu |
| Hasło/konfiguracja SSH, jeśli używane | Lokalny `.env.ssh`, poza Git |
| Tokeny OAuth ChatGPT | PVC `ai-gateway-auth` na serwerze |
| Cookies przeglądarki logowania | Tymczasowy profil w pamięci poda `ai-login` |
| Poświadczenia publikacji GHCR | Lokalny mechanizm poświadczeń Dockera |
| Poświadczenia pobierania obrazów przez k3s | Secret `ghcr-pull` na serwerze |
| Referencje digestów obrazów | `.state/images.json`, bez tokenów |

Nie kopiuj katalogu OAuth na nowy komputer. Nowy klient potrzebuje własnej konfiguracji Caddy/Zeda i dostępu kluczem do istniejącej bramki.

## 14. Rozwiązywanie problemów

### `Unsupported value: 'none' ... gpt-6-astra`

Włącz Thinking w bieżącej rozmowie i wybierz High. Sprawdź wszystkie trzy elementy: `reasoning_effort: high` w modelu, `enable_thinking: true` oraz `effort: high` w `agent.default_model`. `thinking_display` wpływa tylko na wygląd bloków, nie na tryb modelu. Jeśli serwer ma już regułę `none` → `low`, taki błąd nie powinien występować dla Astry; sprawdź zastosowanie konfiguracji opisane poniżej.

### `failed to generate thread title: Unsupported value: 'none'`

Odpowiedź agenta może działać poprawnie, a osobne żądanie tytułu nadal kończyć się błędem. Zed 1.23.3 nie przenosi ustawienia Thinking rozmowy do tego żądania. Poprawka jest po stronie bramki: warunkowa zamiana `none` na `low` dla Astry, opisana w rozdziale 7.5.

Po pobraniu aktualnego repozytorium administrator istniejącej bramki wykonuje:

```sh
make configure MODEL=gpt-6-astra CONTEXT=1050000 OUTPUT=128000
```

Nie wymaga to budowania obrazu ani ponownego logowania ChatGPT. Sprawdź nową rozmowę w Zedzie: powinna otrzymać automatyczny tytuł, a normalna odpowiedź nadal używać High. Samo przełączanie Thinking w starej rozmowie nie naprawia mechanizmu tytułów.

### `Invalid user settings file: missing field prompt_cache_key`

Dodaj `prompt_cache_key: false` wewnątrz `capabilities` każdego skonfigurowanego modelu. Kompletny przykład z rozdziału 7 zawiera to pole.

### `Connection refused` dla `127.0.0.1:8318` albo `8319`

Uruchom `make client` i pozostaw proces działający. Sprawdź nasłuch:

```sh
lsof -nP -iTCP:8318 -iTCP:8319 -sTCP:LISTEN
```

Przy poprawnym działaniu zobaczysz jeden proces Caddy z oboma portami na `127.0.0.1`.

### `address already in use`

Najpierw ustal właściciela portu przez `lsof`. Zatrzymaj poprzedni proces Caddy w jego Terminalu przez `Ctrl+C`. Nie uruchamiaj równolegle dwóch `make client`. Nie zabijaj wszystkich procesów Caddy bez sprawdzenia, czy któryś nie obsługuje innego projektu.

### 401 w Zedzie, mimo że `curl` dociera do bramki

Sprawdź klucz właściwego providera. Klucz zapisany dla portu 8318 nie zastępuje konfiguracji portu 8319. Użyj ponownie `make key-copy`, wklej w odpowiednim providerze i zatwierdź. Pamiętaj, że ręczny `curl` bez klucza ma celowo zwracać 401.

### Brak modeli / `No matches` / `Select a Model`

Sprawdź, czy ustawienia są poprawne i czy oba providery mają zapisany klucz. Po zmianie nazw providerów wybierz model ponownie w bieżącej rozmowie. Jeśli Zed nie odświeży listy po zapisaniu konfiguracji, otwórz nową rozmowę lub uruchom ponownie aplikację po zapisaniu pracy.

Pusty wynik `make models` to osobny problem: serwer może nie mieć zakończonego logowania. Sam ekran zalogowanej przeglądarki nie potwierdza zatwierdzenia kodu urządzenia.

### `Authenticated endpoint works; alias assistant is missing`

Wykonaj `make models`. Jeśli konto jest zalogowane, ustaw konkretny model przez `make configure MODEL=... CONTEXT=... OUTPUT=...`. Jeśli katalog jest pusty, zakończ logowanie. Smoke celowo nie traktuje samego HTTP 200 z katalogu jako sukcesu integracji.

### `no available server`, HTTP 502 albo 503

Sprawdź `make status` i logi Terminala z Caddy. Przyczyną może być zatrzymany pod, niedostępne IP LAN, problem DNS lub brak gotowego backendu. Błąd nie uruchamia alternatywnego bezpośredniego połączenia do OpenAI.

### Network nie działa, Remote działa

Sprawdź, czy jesteś w sieci z trasą do `192.168.1.150`. Możesz sprawdzić LAN z prawidłowym Host i TLS:

```sh
curl --resolve home.mmgt.dev:443:192.168.1.150 -i https://home.mmgt.dev/ca/m
```

Oczekiwane 401 bez klucza oznacza poprawne połączenie. Nie testuj równoważności przez `https://192.168.1.150/ca/m`: certyfikat wystawiono na domenę, a routing wymaga odpowiedniego Host. Nie dodawaj `-k` jako sposobu naprawiania konfiguracji.

### Remote nie działa, Network działa

Sprawdź dostępność DNS i publicznej trasy:

```sh
dscacheutil -q host -a name home.mmgt.dev
curl -i https://home.mmgt.dev/ca/m
```

Network nie zależy od rozwiązania tej domeny dla celu połączenia, ale nadal wymaga aktualnego, zaufanego certyfikatu dla jej nazwy.

### Klucz wklejony, ale Zed nadal nie działa

Sprawdź potwierdzenie `API key configured for ...` i ewentualne okno systemowego pęku kluczy. Zapis przez interfejs Zeda jest właściwą ścieżką. Podczas pierwszej konfiguracji automatyczne operacje narzędziem `security` mogły wymagać osobnej interakcji systemowej, dlatego nie opieramy instrukcji na takim imporcie kluczy.

### `.state/images.json` nie istnieje

To oczekiwane po świeżym `git clone`. Do `make client` i normalnej pracy w Zedzie plik nie jest potrzebny. Do `make login` lub `make deploy` odtwórz go zgodnie z rozdziałem 12.2 albo wygeneruj przez build/push.

### `ai-login already exists` albo zajęty port 33000

Sprawdź, czy wcześniejsze `make login` nadal działa. Zatrzymaj je, jeśli chcesz zakończyć tamtą sesję. Usuń pozostały tymczasowy pod przez `make login-stop`, a port sprawdź poleceniem:

```sh
lsof -nP -iTCP:33000 -sTCP:LISTEN
```

Nie usuwaj PVC ani Deploymentu bramki, żeby wyczyścić sesję przeglądarki.

### Kod logowania wygasł

Zakończ starą próbę i uruchom `make login` ponownie. Użyj nowego kodu. Logowanie musi zakończyć się zatwierdzeniem urządzenia, nie tylko wejściem na konto w Chromium.

### `Authentication completed`, ale pulpit zniknął

To prawidłowe. Skrypt usuwa przeglądarkę i zamyka tunel po udanym logowaniu. Użyj `make models`, a następnie testu generowania; nie próbuj utrzymywać portu 33000 jako stałej usługi.

### `Cannot connect to the Docker daemon`

Dotyczy tylko budowania/publikowania obrazów. Uruchom OrbStack lub używany silnik Dockera i sprawdź `docker info`. Nie trzeba uruchamiać Dockera do samego `make client`.

### `ImagePullBackOff` / błąd publikacji w GHCR

Sprawdź osobno lokalne logowanie Dockera do publikacji oraz serwerowy `ghcr-pull` do pobierania. Zalogowanie `gh` do repozytorium nie jest automatycznym potwierdzeniem dostępu silnika Dockera ani klastra do prywatnego pakietu.

### Agent nadal pyta o zgodę

Sprawdź globalne `agent.tool_permissions.default: allow`, `agent.sandbox_permissions.allow_unsandboxed: true`, profil Write oraz dodatkowe reguły projektu/profilu. Upewnij się, że używasz Zed Agent, a nie zewnętrznego agenta z niezależnym systemem uprawnień.

### Czy Caddy blokuje inne lokalne połączenia do OpenAI?

Nie. Caddy obsługuje tylko ruch skierowany na jego lokalne porty. Nie jest globalną zaporą ruchu wychodzącego dla przeglądarki, terminala czy innych agentów. Taka blokada była omawiana, ale **nie została wdrożona**. Wymagałaby osobnej konfiguracji zapory; nie należy jej mylić z trasami naszej integracji.

## 15. Końcowa lista odbioru nowego Maca

- [ ] Repozytorium jest dostępne, a `.env.ssh` nie jest śledzony przez Git.
- [ ] `make check` kończy się sukcesem.
- [ ] `make client` utrzymuje nasłuch na `127.0.0.1:8318` i `127.0.0.1:8319`.
- [ ] Oba providery w Zedzie mają zapisany klucz naszej bramki.
- [ ] Domyślny wybór to `AI Gateway Network` / `assistant`.
- [ ] W nowej rozmowie Thinking jest włączone i widoczny jest poziom High.
- [ ] `assistant-network` odpowiada przez LAN.
- [ ] `assistant-remote` odpowiada przez domenę.
- [ ] Agent odczytał i zmienił lokalny plik oraz wykonał lokalny test.
- [ ] Full auto działa zgodnie z wybranymi ustawieniami.
- [ ] Klucze nie trafiły do ustawień JSON, Caddyfile ani repozytorium.
- [ ] Tokeny OAuth i sesja przeglądarki ChatGPT nie zostały skopiowane na Maca.
- [ ] Po zakończonym logowaniu nie pozostał potrzebny do pracy tunel 33000.
- [ ] Wiesz, że po restarcie Maca należy ponownie uruchomić `make client`.

## 16. Źródła i pliki referencyjne

- [Repozytorium Code Assistant](https://github.com/nicolas-mgt/code-assistant) — implementacja, którą opisuje instrukcja.
- [Caddy: reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy) — przekazywanie żądań, nagłówki i TLS do adresu IP.
- [Zed: provider OpenAI-compatible](https://github.com/zed-industries/zed/blob/main/crates/language_models/src/provider/open_ai_compatible.rs) — wybór Responses API i obsługa reasoning.
- [Zed: ustawienia agenta](https://github.com/zed-industries/zed/blob/main/crates/settings_content/src/agent.rs) — Thinking, domyślny model i uprawnienia narzędzi.
- [CLIProxyAPI v8.0.28: konfiguracja](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.28/config.example.yaml) — przypięta wersja backendu.
- [CLIProxyAPI v8.0.28: logowanie urządzenia](https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.28/sdk/auth/codex_device.go) — przebieg logowania po stronie serwera.
- [LinuxServer Chromium](https://docs.linuxserver.io/images/docker-chromium/) — obraz zdalnej przeglądarki.

Odnośniki do gałęzi `main` Zeda pokazują bieżący kod upstream. Przy przyszłej aktualizacji aplikacji sprawdź jej aktualny schemat ustawień, jeśli pojawi się błąd walidacji.
