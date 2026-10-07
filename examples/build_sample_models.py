"""Generate the example IFC models in examples/models/.

    python examples/build_sample_models.py

The test suite also imports ``build_licensing_model`` from this file, so the
committed .ifc files and the tests describe the same building.

Model content (the same in both files, only the units differ)
--------------------------------------------------------------
IfcSite "Terreno"              PTMU_Licenciamento.SuperficieTotal = 2000
└─ IfcBuilding "Bloco A"
   ├─ IfcBuildingStorey "Piso 0"
   │   ├─ S01 "Implantação"  USERDEFINED/IMPLANTACAO  (no Afetacao)  GFA 500  NFA 450
   │   ├─ S02 "Fração A"     USERDEFINED/FRACAO       "Comércio"     GFA 120  NFA 100
   │   ├─ S03 "Fração B"     USERDEFINED/FRACAO       "Serviços"     GFA  80  NFA  70
   │   ├─ S04 "Armazém 1"    GFA                      "Logística"    GFA 300  NFA 280
   │   ├─ S09 "Átrio"        INTERNAL                 (no psets, no quantities)
   │   └─ IfcWall "Parede 1"                Qto_WallBaseQuantities.Length = 5 m
   └─ IfcBuildingStorey "Piso 1"
       ├─ S05 "Fração C"     USERDEFINED/FRACAO       "Comércio"     GFA 150  NFA 130
       ├─ S06 "Fração D"     USERDEFINED/FRACAO       (no Afetacao)  GFA  90  NFA  80
       ├─ S07 "Armazém 2"    GFA                      "logistica"    GFA 200  NFA 190
       └─ IfcWallStandardCase "Parede 2"    Qto_WallBaseQuantities.Length = 3 m
└─ IfcBuilding "Bloco B"
   └─ IfcBuildingStorey "Piso 0"
       └─ S08 "Fração E"     NOTDEFINED, typed by IfcSpaceType "Tipo Fração"
                             (USERDEFINED, ElementType FRACAO, type pset Afetacao "Comércio")
                             GFA 60  NFA 55

Areas are in m² (GFA = Qto_SpaceBaseQuantities.GrossFloorArea,
NFA = .NetFloorArea). In the millimetre model the same quantities are
stored in mm and mm², so queries must return identical SI values.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.guid

MODELS_DIR = Path(__file__).parent / "models"

# (id, name, storey key, predefined type, object type, afetacao, GFA m², NFA m²)
SPACES = [
    ("S01", "Implantação", "A0", "USERDEFINED", "IMPLANTACAO", None, 500.0, 450.0),
    ("S02", "Fração A", "A0", "USERDEFINED", "FRACAO", "Comércio", 120.0, 100.0),
    ("S03", "Fração B", "A0", "USERDEFINED", "FRACAO", "Serviços", 80.0, 70.0),
    ("S04", "Armazém 1", "A0", "GFA", None, "Logística", 300.0, 280.0),
    ("S05", "Fração C", "A1", "USERDEFINED", "FRACAO", "Comércio", 150.0, 130.0),
    ("S06", "Fração D", "A1", "USERDEFINED", "FRACAO", None, 90.0, 80.0),
    ("S07", "Armazém 2", "A1", "GFA", None, "logistica", 200.0, 190.0),
    ("S09", "Átrio", "A0", "INTERNAL", None, None, None, None),
]


def _guid(key: str) -> str:
    """Stable GlobalId so regenerated files don't change needlessly."""
    return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"ifcquery-example/{key}").hex)


def build_licensing_model(units: str = "m") -> ifcopenshell.file:
    """Build the sample licensing model. ``units`` is "m" or "mm"."""
    if units not in ("m", "mm"):
        raise ValueError("units must be 'm' or 'mm'")
    length_scale = 1000.0 if units == "mm" else 1.0  # SI value * scale = stored value
    area_scale = length_scale**2

    f = ifcopenshell.api.project.create_file(version="IFC4")

    counter = iter(range(1, 10_000))

    def create(ifc_class: str, name: str, predefined_type: str | None = None):
        e = ifcopenshell.api.root.create_entity(f, ifc_class=ifc_class, name=name, predefined_type=predefined_type)
        e.GlobalId = _guid(f"{units}/{next(counter)}")
        return e

    project = create("IfcProject", "IFCQuery sample")
    prefix = "MILLI" if units == "mm" else None
    ifcopenshell.api.unit.assign_unit(
        f,
        units=[
            ifcopenshell.api.unit.add_si_unit(f, unit_type="LENGTHUNIT", prefix=prefix),
            ifcopenshell.api.unit.add_si_unit(f, unit_type="AREAUNIT", prefix=prefix),
            ifcopenshell.api.unit.add_si_unit(f, unit_type="VOLUMEUNIT", prefix=prefix),
        ],
    )
    ifcopenshell.api.context.add_context(f, context_type="Model")

    site = create("IfcSite", "Terreno")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=project)
    pset = ifcopenshell.api.pset.add_pset(f, product=site, name="PTMU_Licenciamento")
    ifcopenshell.api.pset.edit_pset(f, pset=pset, properties={"SuperficieTotal": 2000.0})

    bloco_a = create("IfcBuilding", "Bloco A")
    bloco_b = create("IfcBuilding", "Bloco B")
    ifcopenshell.api.aggregate.assign_object(f, products=[bloco_a, bloco_b], relating_object=site)

    storeys = {
        "A0": create("IfcBuildingStorey", "Piso 0"),
        "A1": create("IfcBuildingStorey", "Piso 1"),
        "B0": create("IfcBuildingStorey", "Piso 0"),
    }
    ifcopenshell.api.aggregate.assign_object(f, products=[storeys["A0"], storeys["A1"]], relating_object=bloco_a)
    ifcopenshell.api.aggregate.assign_object(f, products=[storeys["B0"]], relating_object=bloco_b)

    def add_areas(space, gfa: float, nfa: float) -> None:
        qto = ifcopenshell.api.pset.add_qto(f, product=space, name="Qto_SpaceBaseQuantities")
        ifcopenshell.api.pset.edit_qto(
            f, qto=qto, properties={"GrossFloorArea": gfa * area_scale, "NetFloorArea": nfa * area_scale}
        )

    def add_afetacao(product, value: str) -> None:
        p = ifcopenshell.api.pset.add_pset(f, product=product, name="PTMU_Licenciamento")
        ifcopenshell.api.pset.edit_pset(f, pset=p, properties={"Afetacao": value})

    for key, name, storey, predefined, object_type, afetacao, gfa, nfa in SPACES:
        space = create("IfcSpace", name, predefined)
        space.Description = key
        if object_type:
            space.ObjectType = object_type
        ifcopenshell.api.aggregate.assign_object(f, products=[space], relating_object=storeys[storey])
        if afetacao:
            add_afetacao(space, afetacao)
        if gfa is not None:
            add_areas(space, gfa, nfa)

    # S08: classification comes from its type object, not the occurrence.
    space_type = create("IfcSpaceType", "Tipo Fração", "USERDEFINED")
    space_type.ElementType = "FRACAO"
    add_afetacao(space_type, "Comércio")
    s08 = create("IfcSpace", "Fração E", "NOTDEFINED")
    s08.Description = "S08"
    ifcopenshell.api.aggregate.assign_object(f, products=[s08], relating_object=storeys["B0"])
    ifcopenshell.api.type.assign_type(f, related_objects=[s08], relating_type=space_type)
    add_areas(s08, 60.0, 55.0)

    # Walls: IfcWallStandardCase is a subtype of IfcWall in IFC4.
    for ifc_class, name, storey, length in (
        ("IfcWall", "Parede 1", "A0", 5.0),
        ("IfcWallStandardCase", "Parede 2", "A1", 3.0),
    ):
        wall = create(ifc_class, name)
        ifcopenshell.api.spatial.assign_container(f, products=[wall], relating_structure=storeys[storey])
        qto = ifcopenshell.api.pset.add_qto(f, product=wall, name="Qto_WallBaseQuantities")
        ifcopenshell.api.pset.edit_qto(f, qto=qto, properties={"Length": length * length_scale})

    return f


def main() -> None:
    MODELS_DIR.mkdir(exist_ok=True)
    for units, filename in (("m", "licensing_sample.ifc"), ("mm", "millimetre_units.ifc")):
        path = MODELS_DIR / filename
        build_licensing_model(units).write(str(path))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
