"""Rule vocabulary of the training knowledge base (coach spec 3.3).

Every ``regel.typ`` is one Pydantic class; YAML may only use these types and the fixed
quantity names below -- no free expressions, no code. A new type needs a new class and a
test.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sport = Literal["laufen", "rad", "schwimmen", "kraft", "yoga", "alle"]
Art = Literal["leitplanke", "regel", "parameter", "einheit", "test"]
Evidenz = Literal["hoch", "mittel", "niedrig", "praxis"]
Zone3 = Literal["z1", "z2", "z3"]
# Daniels running intensities; "G" is walking/standing recovery inside a workout
Tempo = Literal["E", "M", "T", "I", "R", "G"]
PhaseArt = Literal["basis", "aufbau", "spitze", "taper", "wettkampf", "uebergang"]
Bezugswert = Literal["vdot", "lthr_laufen", "lthr_rad", "ftp", "css", "critical_speed", "hf_max"]

# quantities the validator can measure on a plan week or a single session
Groesse = Literal[
    "zeit.z1",
    "zeit.z2",
    "zeit.z3",
    "zeit.gesamt",
    "lauf.distanz_m",
    "lauf.dauer_s",
    "woche.lauf_distanz_m",
    "woche.lauf_dauer_s",
]

# formulas implemented in kairos.coach.zones -- referenced by name only
Formel = Literal["daniels_gilbert_vdot", "lthr_letzte_20min", "ftp_20min", "css_wakayoshi"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Spanne(_Model):
    min: float
    max: float

    @model_validator(mode="after")
    def _ordered(self) -> Spanne:
        if self.min > self.max:
            raise ValueError("min > max")
        return self


class AnteilMin(_Model):
    typ: Literal["anteil_min"]
    groesse: Groesse
    bezug: Groesse
    wert: float = Field(ge=0, le=1)
    fenster: Literal["woche"] = "woche"


class AnteilMax(_Model):
    typ: Literal["anteil_max"]
    groesse: Groesse
    bezug: Groesse
    wert: float = Field(ge=0, le=1)
    fenster: Literal["woche"] = "woche"


class Bezug(_Model):
    funktion: Literal["max", "mittel"]
    groesse: Groesse
    fenster_tage: int = Field(ge=1, le=365)


class ObergrenzeRelativ(_Model):
    typ: Literal["obergrenze_relativ"]
    groesse: Groesse
    bezug: Bezug
    faktor: float = Field(gt=0)
    aktion: Literal["kuerzen", "warnen"]


class ObergrenzeAbsolut(_Model):
    typ: Literal["obergrenze_absolut"]
    groesse: Groesse
    wert: float = Field(gt=0)


class ZuwachsMax(_Model):
    typ: Literal["zuwachs_max"]
    groesse: Groesse
    vergleich: Literal["vorwoche", "schnitt_n_wochen"]
    n: int = Field(1, ge=1, le=12)
    faktor: float = Field(gt=1)


class Rhythmus(_Model):
    typ: Literal["rhythmus"]
    zyklus: int = Field(ge=2, le=8)
    position: int = Field(ge=1)
    aenderung: float = Field(gt=-1, lt=0)

    @model_validator(mode="after")
    def _position_in_cycle(self) -> Rhythmus:
        if self.position > self.zyklus:
            raise ValueError("position > zyklus")
        return self


class PhaseDef(_Model):
    art: PhaseArt
    anteil: float = Field(gt=0, le=1)
    min_wochen: int = Field(ge=0)
    max_wochen: int = Field(ge=1)
    schwerpunkt: str
    # quality units the generator may pick in this phase, in priority order
    qualitaet: list[str] = Field(default_factory=list)


class Phase(_Model):
    typ: Literal["phase"]
    phasen: list[PhaseDef] = Field(min_length=1)


class Taper(_Model):
    typ: Literal["taper"]
    tage: Spanne
    umfang_aenderung: Spanne
    intensitaet: Literal["halten"] = "halten"


class ZoneDef(_Model):
    name: str
    zone3: Zone3
    von: float = Field(ge=0)
    bis: float = Field(gt=0)


class Zonen(_Model):
    typ: Literal["zonen"]
    bezugswert: Bezugswert
    einheit: Literal["prozent_vo2max", "prozent_lthr", "prozent_hfmax"]
    zonen: list[ZoneDef] = Field(min_length=1)


class Test(_Model):
    typ: Literal["test"]
    bezugswert: Bezugswert
    protokoll: str
    formel: Formel
    distanz_m: Spanne | None = None


class Schritt(_Model):
    """Slim step model until the Kairos workout model of stage 1 D.1 exists."""

    typ: Literal["einlaufen", "belastung", "pause", "auslaufen", "wiederholung"]
    tempo: Tempo | None = None
    dauer_s: float | None = Field(None, gt=0)
    distanz_m: float | None = Field(None, gt=0)
    # the generator sets the size of this step from the planned volume
    variabel: bool = False
    wiederholungen: int | None = Field(None, ge=1, le=40)
    schritte: list[Schritt] | None = None
    notiz: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _shape(self) -> Schritt:
        if self.typ == "wiederholung":
            if not self.schritte or self.wiederholungen is None:
                raise ValueError("wiederholung braucht schritte und wiederholungen")
        elif self.schritte:
            raise ValueError("nur wiederholung hat schritte")
        elif not self.variabel and self.dauer_s is None and self.distanz_m is None:
            raise ValueError("schritt braucht dauer_s, distanz_m oder variabel")
        return self


class Einheit(_Model):
    typ: Literal["einheit"]
    sport: Sport
    zone: Zone3
    # workout_type in plan_block (coarse class for calendar and situation brief)
    klasse: Literal["long_run", "quality", "easy", "strength", "test"]
    struktur: list[Schritt] = Field(min_length=1)
    anteil_max_woche: float | None = Field(None, gt=0, le=1)
    dauer_s: Spanne | None = None


class AbstandMin(_Model):
    typ: Literal["abstand_min"]
    von: list[str] = Field(min_length=1)
    zu: list[str] = Field(min_length=1)
    stunden: float = Field(gt=0)


class Haeufigkeit(_Model):
    typ: Literal["haeufigkeit"]
    einheiten: list[str] = Field(min_length=1)
    min: int = Field(ge=0)
    max: int = Field(ge=0)
    phasen: list[PhaseArt] | None = None


RegelTeil = Annotated[
    AnteilMin
    | AnteilMax
    | ObergrenzeRelativ
    | ObergrenzeAbsolut
    | ZuwachsMax
    | Rhythmus
    | Phase
    | Taper
    | Zonen
    | Test
    | Einheit
    | AbstandMin
    | Haeufigkeit,
    Field(discriminator="typ"),
]


class EntryHead(_Model):
    id: str = Field(pattern=r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
    version: int = Field(ge=1)
    titel: str = Field(min_length=3)
    sportarten: list[Sport] = Field(min_length=1)
    art: Art
    evidenz: Evidenz
    quellen: list[str] = Field(min_length=1)
    regel: RegelTeil


class PlanTypeHead(_Model):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    version: int = Field(ge=1)
    titel: str
    hauptsport: Literal["laufen", "rad", "triathlon"]
    ziele: list[Literal["wettkampf", "gesundheit", "einsteiger"]] = Field(min_length=1)
    bezugswerte: dict[Literal["pflicht", "optional"], list[Bezugswert]]
    parameter: dict[str, object]
    regeln: list[str] = Field(min_length=1)
    phasen: str
    zonen: list[str] = Field(min_length=1)
    tests: list[str] = Field(default_factory=list)
    einheiten: list[str] = Field(min_length=1)
