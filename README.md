# CNAIR eToll 2026 pentru Home Assistant

Integrare custom pentru [Home Assistant](https://www.home-assistant.io/) care citește contul tău [eToll](https://etoll.ro) (sistemul CNAIR care, din 1 octombrie 2026, înlocuiește erovinieta) și afișează rovinieta vehiculelor tale: **data de expirare, zilele rămase, numărul de înmatriculare, VIN-ul** și alte date utile.

> **Neoficială.** Proiect independent, fără legătură cu CNAIR. Folosește aceleași cereri ca portalul `etoll.ro` (API nedocumentat, care se poate schimba fără notificare). Doar **citește** informații: nu cumpără roviniete și nu modifică nimic în cont.

## Ce primești

Un dispozitiv pentru cont și câte unul pentru fiecare vehicul din cont.

**Per vehicul**

| Entitate | Conținut |
|---|---|
| Rovinietă valabilă până la | data expirării (senzor de tip dată, afișat conform setărilor HA); atribute: număr, ora exactă, zile rămase, valabilă de la, perioadă, stare, preț plătit, serie rovinietă, data achiziției |
| Rovinietă zile rămase | zile calendaristice până la expirare (negativ după expirare) |
| Rovinietă expirare (timestamp) | același moment ca timestamp, pentru automatizări (dezactivat implicit) |
| Rovinietă activă | senzor binar, pornit cât rovinieta e valabilă |
| Număr înmatriculare, VIN, Serie certificat înmatriculare | datele vehiculului (VIN și seria certificatului sunt dezactivate implicit, categorie „diagnostic”) |
| Categorie vehicul | A, B, C, D, I, II, III; atribute: categoria pentru poduri, tip vehicul, masa maximă |
| Clasă de emisii | ex. Euro 6 |
| Cheltuieli în anul curent | total, defalcat pe roviniete / poduri / tichete de rută, totaluri pe ani |
| Probleme date vehicul | pornit când contul marchează datele vehiculului ca invalide |

**Per cont:** notificări necitite, ultima factură (sumă, număr, metodă de plată, TVA), total plătit în anul curent.

Data de expirare vine din eligibilitatea vehiculului, deci apare corect și pentru rovinietele cumpărate din alt canal (SMS, benzinărie, distribuitori), nu doar din contul tău.

## Instalare

Necesită Home Assistant **2026.3** sau mai nou.

**HACS (repository personalizat)**
1. HACS → ⋮ → *Custom repositories* → adaugă `https://github.com/alexandruviziteu/ha-etoll-cnair`, categoria *Integration*.
2. Instalează „CNAIR eToll 2026” și repornește Home Assistant.

**Manual:** copiază `custom_components/etoll_cnair` în `config/custom_components/` și repornește.

## Configurare

*Setări → Dispozitive și servicii → Adaugă integrare → CNAIR eToll 2026*, apoi emailul și parola contului etoll.ro.

- Parola se păstrează în Home Assistant (în intrarea de configurare), ca la orice integrare cloud, și se folosește la autentificarea la `sso.etoll.ro`.
- Funcționează doar cu conturi **cu parolă**. Conturile create exclusiv prin Google, ROeID sau eIDAS nu au parolă eToll și nu sunt suportate.
- Intervalul de actualizare e 60 de minute (se schimbă din *Configurare*, minimum 15).
- Numele apar în română când Home Assistant e setat pe română, altfel în engleză.

## Dezinstalare

1. *Setări → Dispozitive și servicii → CNAIR eToll 2026* → ⋮ → **Șterge**. Se elimină intrarea de configurare (inclusiv parola salvată în ea), dispozitivele și entitățile.
2. Dacă ai instalat prin HACS: HACS → CNAIR eToll 2026 → ⋮ → *Remove*. Instalat manual: șterge folderul `config/custom_components/etoll_cnair`.
3. Repornește Home Assistant. Integrarea nu creează fișiere sau date în afara configurației HA, deci nu rămâne nimic de curățat în contul eToll.

## Dispozitive și servicii suportate

- Serviciul **eToll** (`etoll.ro`, CNAIR), prin contul tău cu email și parolă.
- Toate vehiculele din cont, indiferent de categorie (A, B, C, D, I, II, III). Fiecare vehicul devine un dispozitiv separat.
- Doar citire: integrarea nu are acțiuni (servicii) și nu cumpără sau modifică nimic.

## Actualizarea datelor

Integrarea interoghează portalul (*cloud polling*) la fiecare 60 de minute, cu un singur ciclu de cereri pentru tot contul. Intervalul se schimbă din *Configurare* (minimum 15 minute). Dacă portalul nu răspunde temporar, entitățile păstrează ultimele valori cunoscute pentru datele secundare (vehicule, facturi) și devin indisponibile doar când datele principale nu pot fi citite.

## Depanare

| Simptom | Cauză probabilă și remediu |
|---|---|
| „Email sau parolă invalidă” la configurare | Verifică datele pe etoll.ro. Conturile create doar prin Google, ROeID sau eIDAS nu au parolă și nu merg. |
| „Nu se poate conecta la etoll.ro” | Portalul sau rețeaua nu răspund; încearcă din nou mai târziu. |
| Notificare de reautentificare | Ai schimbat parola pe etoll.ro. Deschide notificarea din Home Assistant și introdu parola nouă. |
| Entitățile sunt indisponibile | Portalul poate fi temporar indisponibil sau a modificat API-ul. Vezi jurnalul și, dacă persistă, deschide o problemă pe GitHub. |
| Automatizarea nu mai merge după actualizarea la 0.2.0 | Starea „Rovinietă valabilă până la” este acum dată, nu text; vezi [CHANGELOG](CHANGELOG.md). |

**Jurnal de depanare.** Adaugă în `configuration.yaml`, repornește și reproduce problema:

```yaml
logger:
  default: warning
  logs:
    custom_components.etoll_cnair: debug
```

Parola nu apare în jurnale. Când raportezi o problemă, atașează doar liniile relevante și șterge orice dată personală (număr de înmatriculare, VIN, email).

## Exemplu: avertizare înainte de expirare

```yaml
automation:
  - alias: "Rovinieta expiră curând"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.rovinieta_xx00xxx_rovinieta_zile_ramase   # ajustează ID-ul
        below: 15
    actions:
      - action: notify.notify
        data:
          title: "Rovinieta expiră"
          message: >
            Mai sunt {{ states('sensor.rovinieta_xx00xxx_rovinieta_zile_ramase') }} zile.
```

Verifică ID-urile reale în *Setări → Dispozitive și servicii → CNAIR eToll 2026*.

## Limitări

- API nedocumentat: CNAIR îl poate modifica sau restricționa; integrarea poate înceta să funcționeze fără avertisment.
- Autentificarea cu parolă trebuie să rămână permisă de serverul `sso.etoll.ro`.
- Se citesc primele 50 de servicii și vehicule pe pagină (cu paginare); istoricul foarte vechi nu e acoperit.
- Vehiculele noi adăugate în cont apar automat la următoarea actualizare. Cele șterse din cont rămân ca dispozitive în Home Assistant până le ștergi manual.

## Dezvoltare și licență

Cod sub licență [MIT](LICENSE). Contribuțiile și raportările de probleme sunt binevenite.

---

## English

Unofficial Home Assistant integration for the Romanian **eToll / TollRo** portal (`etoll.ro`, CNAIR). It reads your account (email + password login) and exposes, per vehicle, the vignette (*rovinietă*) expiry date, days left, plate number, VIN, registration certificate, category, emission class and yearly spending, plus unread notifications and invoices for the account. Read-only; uses the same undocumented API as the portal, so it may break without notice. Accounts that only use Google/ROeID/eIDAS sign-in (no password) are not supported. Install via HACS (custom repository) or by copying `custom_components/etoll_cnair`. Not affiliated with CNAIR. MIT licensed.
