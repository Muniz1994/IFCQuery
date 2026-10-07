# Revised DSL: language summary

The language queries IFC models. A **query** selects elements by class, narrows them with a **filter**, optionally moves through the spatial hierarchy with **containment**, and extracts values with a **projection**. **Aggregate functions** reduce lists to numbers, and **bindings and arithmetic** combine results into rule checks.

```
SUM(IfcSpace[PredefinedType = GFA and PTMU_Licenciamento.Afetacao = "Logística"]
    -> Qto_SpaceBaseQuantities.GrossFloorArea)
```

## Lexical conventions

Comments start with `//` and run to the end of the line. `#` is not used, so it stays free for STEP instance references later.

Whitespace is insignificant, except that newlines separate statements. Keywords (`and`, `or`, `not`, `in`, `let`) and function names are case-insensitive. By convention functions are written in uppercase.

Identifiers may contain Unicode letters, so `Afetação` is valid. Names with spaces or other special characters go in double quotes when used as identifiers, e.g. `"Identity Data"."Assembly Code"`. Any identifier beginning with `Ifc` is an IFC class name, which is how the parser tells classes apart from variables.

Literals come in four kinds, and the distinction matters:

| Kind | Examples | Notes |
|---|---|---|
| String | `"IMPLANTACAO"`, `"Comércio e Serviços"` | Always double-quoted |
| Number | `100`, `0.6`, `-2.5` | Compared numerically |
| Boolean | `true`, `false` | For boolean properties |
| Enumeration | `USERDEFINED`, `GFA`, `NOTDEFINED` | Bare uppercase word, checked against the IFC schema at parse time |

Because enumerations are bare and strings are quoted, a typo like `PredefinedType = GFAA` becomes a parse-time error instead of a silent empty result.

## Entity selector

A selector is an IFC class name and returns every element of that class, **including subtypes**. `IfcWall` therefore also matches `IfcWallStandardCase`. Class names are case-insensitive, matching how STEP files store them.

```
IfcSite
IfcSpace
IfcBuildingElement      // walls, slabs, columns, doors, ...
```

## Filter block

A filter in square brackets after a class keeps only the elements for which the condition is true.

```
IfcSpace[PredefinedType = USERDEFINED and ObjectType = "FRACAO"]
```

A condition compares a **path** with a literal. A path is either a direct IFC attribute (`Name`, `ObjectType`, `PredefinedType`) or a property-set property written `PropertySet.Property` (`PTMU_Licenciamento.Afetacao`, `Qto_SpaceBaseQuantities.GrossFloorArea`). The two cannot collide, because a dotted path always means "property inside a property set."

| Operator | Meaning |
|---|---|
| `=`, `!=` | Equal, not equal (exact, case-sensitive for strings) |
| `<`, `<=`, `>`, `>=` | Numeric comparison |
| `~=` | Case- and accent-insensitive string equality (`"logistica" ~= "Logística"` is true) |
| `in (a, b, …)` | Equal to any of the listed values |
| `exists(path)` | The element has this attribute or property |

Conditions combine with `and`, `or`, and `not`, with parentheses for grouping. Precedence is `not`, then `and`, then `or`.

```
IfcSpace[PTMU_Licenciamento.Afetacao in ("Comércio", "Serviços")
         and Qto_SpaceBaseQuantities.GrossFloorArea >= 100]

IfcSpace[not exists(PTMU_Licenciamento.Afetacao)]   // spaces missing the property
```

**Property resolution.** When looking up `Pset.Property`, the value on the element itself is used first. If it's absent there, the value from the element's type object (e.g. its `IfcSpaceType`) is used. This follows the IFC rule that occurrence values override type values.

**User-defined types.** Comparing `PredefinedType` with a *string* rather than an enumeration means "the user-defined type." So these two filters are equivalent:

```
IfcSpace[PredefinedType = USERDEFINED and ObjectType = "IMPLANTACAO"]
IfcSpace[PredefinedType = "IMPLANTACAO"]
```

This is the same convention buildingSMART's IDS uses.

## Containment: `>`

`A > B` returns the elements matching `B` that sit anywhere below the elements matching `A` in the spatial hierarchy. This covers both aggregation (`IfcRelAggregates`) and spatial containment (`IfcRelContainedInSpatialStructure`), at any depth. Each side may have its own filter, and chains read left to right.

```
IfcBuildingStorey[Name = "Piso 0"] > IfcSpace
IfcBuilding[Name = "Bloco A"] > IfcBuildingStorey > IfcSpace[ObjectType = "FRACAO"]
```

The parser treats `>` as containment only when the next token is an IFC class name. Otherwise it is the greater-than operator. Inside filters `>` is always greater-than.

## Projection: `->`

`->` turns a list of elements into a list of values. The path follows the same rules as in filters.

```
IfcSite -> PTMU_Licenciamento.SuperficieTotal
IfcSpace -> Name
```

Several paths in parentheses produce a list of records, which is useful for listings and debugging:

```
IfcSpace[ObjectType = "FRACAO"] -> (Name, PTMU_Licenciamento.Afetacao, Qto_SpaceBaseQuantities.NetFloorArea)
```

An element without the requested value contributes `null`, so the result always has one entry per element. Quantities (`Qto_` sets) return their numeric value converted to SI units (m, m², m³), whatever units the file uses.

## Aggregate functions

Aggregates reduce a list to a single value.

| Function | Input | Result |
|---|---|---|
| `COUNT(x)` | Element list or value list | Number of elements, or number of non-null values |
| `SUM(x)`, `AVG(x)`, `MIN(x)`, `MAX(x)` | Numeric value list | Ignores nulls; `SUM` of an empty list is 0, the others return null |
| `FIRST(x)` | Any list | First non-null entry, for quantities expected to be single (e.g. the site area) |

Type errors are caught before evaluation. `SUM(IfcSpace)` is rejected because an element list isn't numeric.

## Bindings, arithmetic, and rules

`let` names a result for later statements. Expressions support `+ - * /` with normal precedence, and comparisons. A statement that evaluates to a boolean is a **rule check**: it passes when true.

```
let implantacao = SUM(IfcSpace[PredefinedType = "IMPLANTACAO"] -> Qto_SpaceBaseQuantities.GrossFloorArea)
let terreno     = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
implantacao / terreno <= 0.6
```

## Value types

Every expression has one of four types, and functions and operators check them.

| Type | Produced by | Example |
|---|---|---|
| Element list | Selector, filter, containment | `IfcSpace[...]` |
| Value list | Projection | `IfcSpace -> Name` |
| Scalar | Aggregates, literals, arithmetic | `SUM(...)`, `0.6` |
| Boolean | Comparisons | `a / b <= 0.6` |

## The original examples, revised

```
// Total area of the site, from the municipal licensing property set
IfcSite -> PTMU_Licenciamento.SuperficieTotal

// Gross floor area of each implantation space
IfcSpace[PredefinedType = "IMPLANTACAO"] -> Qto_SpaceBaseQuantities.GrossFloorArea

// Number of commercial fractions
COUNT(IfcSpace[PredefinedType = "FRACAO" and PTMU_Licenciamento.Afetacao = "Comércio"])

// Total gross floor area used for logistics
SUM(IfcSpace[PredefinedType = GFA and PTMU_Licenciamento.Afetacao = "Logística"]
    -> Qto_SpaceBaseQuantities.GrossFloorArea)
```

## Further examples

```
// Fractions on the ground floor, by name and use
IfcBuildingStorey[Name = "Piso 0"] > IfcSpace[PredefinedType = "FRACAO"]
  -> (Name, PTMU_Licenciamento.Afetacao)

// Tolerant matching for inconsistently typed values
COUNT(IfcSpace[PTMU_Licenciamento.Afetacao ~= "logistica"])

// Data-quality check: every fraction must declare its use
COUNT(IfcSpace[PredefinedType = "FRACAO" and not exists(PTMU_Licenciamento.Afetacao)]) = 0

// Building-use index: total gross floor area over site area
let abc     = SUM(IfcSpace[PredefinedType = GFA] -> Qto_SpaceBaseQuantities.GrossFloorArea)
let terreno = FIRST(IfcSite -> PTMU_Licenciamento.SuperficieTotal)
abc / terreno <= 1.2
```

## Grammar sketch (EBNF)

```ebnf
program     = { statement NEWLINE } ;
statement   = "let" VAR "=" expr | expr ;

expr        = additive [ compop additive ] ;
additive    = term { ( "+" | "-" ) term } ;
term        = unary { ( "*" | "/" ) unary } ;
unary       = [ "-" ] primary ;
primary     = NUMBER | STRING | VAR | call | query | "(" expr ")" ;
call        = FUNC "(" expr ")" ;

query       = selection [ "->" projection ] ;
selection   = entity { ">" entity } ;          (* ">" followed by IFCCLASS *)
entity      = IFCCLASS [ "[" condition "]" ] ;
projection  = path | "(" path { "," path } ")" ;

condition   = andcond { "or" andcond } ;
andcond     = notcond { "and" notcond } ;
notcond     = [ "not" ] atom ;
atom        = path compop literal
            | path "in" "(" literal { "," literal } ")"
            | "exists" "(" path ")"
            | "(" condition ")" ;

path        = name [ "." name ] ;
name        = IDENT | QUOTED_IDENT ;
literal     = STRING | NUMBER | BOOLEAN | ENUM ;
compop      = "=" | "!=" | "<" | "<=" | ">" | ">=" | "~=" ;
```
## Implementation notes

These points are not settled by the sections above. The reference implementation (`src/ifcquery`) resolves them as follows.

- **Line continuation.** Newlines inside `( )` and `[ ]` are ignored. A line that starts with a binary operator (`->`, `>`, `<`, `=`, `!=`, `~=`, `+`, `*`, `/`, `and`, `or`) continues the previous statement. This is what lets `-> (Name, ...)` sit on its own line. A line starting with `-` begins a new statement, because `-` may be a unary minus.
- **Missing values in filters.** Every comparison against a missing value is false, including `!=`. `not exists(...)` is the way to find elements that lack a value.
- **Missing values in rules.** Arithmetic with a missing operand gives null, and so does division by zero. A rule whose comparison meets a null is *inconclusive* (`passed = None`) rather than false.
- **`PredefinedType` fallback.** When the occurrence's value is empty or `NOTDEFINED`, the type object's value is used. For a string comparison, the user-defined name is the occurrence's `ObjectType`, or the type's `ElementType` when the value comes from the type. A string never matches a non-`USERDEFINED` value, so `PredefinedType != "FRACAO"` is true for a `GFA` space.
- **Enumerations on properties.** A bare enumeration literal compared with `Pset.Property` can't be checked against the schema, because property sets are open. It is compared as text.
- **Attribute names** in non-dotted paths are checked at parse time against the class's attributes, inherited ones included. They are case-sensitive, as in the IFC schema.
- **Ordering operators** (`<`, `<=`, `>`, `>=`) in filters require a number literal. In rules they require numeric operands at run time.
- **Projection in parentheses** always produces records, even with a single path: `-> (Name)`.
- **Multi-valued properties** (list or enumerated values with several items) match when any item matches.
- **Units.** Values from any `IfcElementQuantity`, not only sets named `Qto_`, are converted to SI (m, m², m³, kg, s). Other property values are returned as stored.
- **Containment** follows `IfcRelAggregates` and `IfcRelContainedInSpatialStructure`. The elements on the left of `>` are not part of the result.
- **Reserved words.** `let`, `and`, `or`, `not`, `in`, `exists`, `true`, `false` and the function names are reserved in any case. Quote them to use them as property names, e.g. `Pset."Count"`.
