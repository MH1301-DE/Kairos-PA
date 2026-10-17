# CalDAV-Fixtures (AP 0)

Erzeugt von `scripts/caldav_verify.py` gegen das iCloud-Konto von Nutzer 0, anonymisiert
vor dem Schreiben (Apple-ID, numerische Konto-ID, Kalendernamen und -IDs, E-Mail-Adressen,
`CN=`, `urn:uuid:`, `tel:`). Enthalten sind nur Antworten zu Wegwerf-Terminen des Skripts
(UID endet auf `-kairos-ap0`); Antworten aus fremden Kalendern werden auf diese gefiltert.

Neu erzeugen: siehe Kopf von `scripts/caldav_verify.py`. Vor dem Einchecken
`rg -n "@icloud|@me.com|@mac.com" tests/fixtures/caldav` prüfen (muss leer sein).
