"""Tests for OWL Turtle serialization/deserialization round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from arango_query_core.mapping import MappingBundle
from arango_query_core.owl_turtle import mapping_to_turtle, turtle_to_mapping

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "mappings"


@pytest.fixture
def simple_bundle() -> MappingBundle:
    return MappingBundle(
        conceptual_schema={
            "entities": [
                {
                    "name": "Person",
                    "labels": ["Person"],
                    "properties": [
                        {"name": "name", "type": "string"},
                        {"name": "age", "type": "integer"},
                    ],
                },
                {
                    "name": "Movie",
                    "labels": ["Movie"],
                    "properties": [
                        {"name": "title", "type": "string"},
                        {"name": "released", "type": "integer"},
                    ],
                },
            ],
            "relationships": [
                {
                    "type": "ACTED_IN",
                    "fromEntity": "Person",
                    "toEntity": "Movie",
                    "properties": [{"name": "roles", "type": "string"}],
                },
            ],
        },
        physical_mapping={
            "entities": {
                "Person": {"collectionName": "persons", "style": "COLLECTION"},
                "Movie": {"collectionName": "movies", "style": "COLLECTION"},
            },
            "relationships": {
                "ACTED_IN": {
                    "edgeCollectionName": "acted_in",
                    "style": "DEDICATED_COLLECTION",
                },
            },
        },
        metadata={"provider": "test"},
    )


def test_export_contains_classes(simple_bundle: MappingBundle) -> None:
    ttl = mapping_to_turtle(simple_bundle)
    assert ":Person a owl:Class" in ttl
    assert ":Movie a owl:Class" in ttl
    assert ":ACTED_IN a owl:ObjectProperty" in ttl
    assert 'phys:collectionName "persons"' in ttl
    assert 'phys:edgeCollectionName "acted_in"' in ttl


def test_export_contains_properties(simple_bundle: MappingBundle) -> None:
    ttl = mapping_to_turtle(simple_bundle)
    assert ":name a owl:DatatypeProperty" in ttl
    assert "xsd:string" in ttl
    assert ":age a owl:DatatypeProperty" in ttl
    assert "xsd:integer" in ttl


def test_roundtrip_preserves_entities(simple_bundle: MappingBundle) -> None:
    ttl = mapping_to_turtle(simple_bundle)
    restored = turtle_to_mapping(ttl)

    entity_names = {e["name"] for e in restored.conceptual_schema["entities"]}
    assert entity_names == {"Person", "Movie"}

    pm = restored.physical_mapping
    assert pm["entities"]["Person"]["collectionName"] == "persons"
    assert pm["entities"]["Movie"]["collectionName"] == "movies"


def test_roundtrip_preserves_relationships(simple_bundle: MappingBundle) -> None:
    ttl = mapping_to_turtle(simple_bundle)
    restored = turtle_to_mapping(ttl)

    rels = restored.conceptual_schema["relationships"]
    assert len(rels) == 1
    assert rels[0]["type"] == "ACTED_IN"
    assert rels[0]["fromEntity"] == "Person"
    assert rels[0]["toEntity"] == "Movie"

    pm = restored.physical_mapping
    assert pm["relationships"]["ACTED_IN"]["edgeCollectionName"] == "acted_in"
    assert pm["relationships"]["ACTED_IN"]["style"] == "DEDICATED_COLLECTION"


def test_roundtrip_preserves_entity_properties(simple_bundle: MappingBundle) -> None:
    ttl = mapping_to_turtle(simple_bundle)
    restored = turtle_to_mapping(ttl)

    person = next(e for e in restored.conceptual_schema["entities"] if e["name"] == "Person")
    prop_names = {p["name"] for p in person["properties"]}
    assert "name" in prop_names
    assert "age" in prop_names


def test_import_existing_fixture() -> None:
    ttl_path = _FIXTURES_DIR / "pg.owl.ttl"
    if not ttl_path.exists():
        pytest.skip("pg.owl.ttl fixture not found")

    ttl = ttl_path.read_text(encoding="utf-8")
    bundle = turtle_to_mapping(ttl)

    entity_names = {e["name"] for e in bundle.conceptual_schema["entities"]}
    assert "Person" in entity_names
    assert "User" in entity_names

    assert len(bundle.conceptual_schema["relationships"]) >= 1
    follows = next(r for r in bundle.conceptual_schema["relationships"] if r["type"] == "FOLLOWS")
    assert follows["fromEntity"] == "Any"

    assert bundle.physical_mapping["entities"]["Person"]["collectionName"] == "persons"
    assert bundle.physical_mapping["relationships"]["FOLLOWS"]["edgeCollectionName"] == "follows"


def test_export_label_style() -> None:
    bundle = MappingBundle(
        conceptual_schema={
            "entities": [
                {"name": "Person", "labels": ["Person"], "properties": []},
            ],
            "relationships": [],
        },
        physical_mapping={
            "entities": {
                "Person": {
                    "collectionName": "nodes",
                    "style": "LABEL",
                    "typeField": "type",
                    "typeValue": "Person",
                },
            },
            "relationships": {},
        },
        metadata={},
    )
    ttl = mapping_to_turtle(bundle)
    assert 'phys:mappingStyle "LABEL"' in ttl
    assert 'phys:typeField "type"' in ttl
    assert 'phys:typeValue "Person"' in ttl

    restored = turtle_to_mapping(ttl)
    pm_p = restored.physical_mapping["entities"]["Person"]
    assert pm_p["style"] == "LABEL"
    assert pm_p["typeField"] == "type"
    assert pm_p["typeValue"] == "Person"


# ---------------------------------------------------------------------------
# Property names, shared fields and stored-field names (import fixes)
# ---------------------------------------------------------------------------

# The layout arangodb-schema-analyzer >= 0.15.1 writes: a field two classes
# share has an owl:unionOf domain; a renamed or sanitized field carries its
# stored name in phys:attributeName.
ANALYZER_OWL = """\
@prefix : <http://arangodb.com/schema/hybrid#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix phys: <http://arangodb.com/schema/physical#> .

:Chunk a owl:Class ;
  rdfs:label "Chunk" .
:Chunk phys:mappingStyle "COLLECTION" .
:Chunk phys:collectionName "chunks" .

:Document a owl:Class ;
  rdfs:label "Document" .
:Document phys:mappingStyle "COLLECTION" .
:Document phys:collectionName "documents" .

:content a owl:DatatypeProperty ;
  rdfs:label "content" ;
  rdfs:domain [ a owl:Class ; owl:unionOf ( :Chunk :Document ) ] .

:file_name a owl:DatatypeProperty ;
  rdfs:label "file-name" ;
  rdfs:domain :Document .
:file_name phys:attributeName "file-name" .

:page_count a owl:DatatypeProperty ;
  rdfs:label "page_count" ;
  rdfs:domain :Document ;
  rdfs:range xsd:integer .
"""


def _props(bundle: MappingBundle, entity: str) -> list[str]:
    return [
        p["name"]
        for e in bundle.conceptual_schema["entities"]
        if e["name"] == entity
        for p in e["properties"]
    ]


def test_snake_case_entity_properties_keep_their_names(simple_bundle: MappingBundle) -> None:
    """Regression: every name was cut at its last underscore (file_name -> name)."""
    simple_bundle.conceptual_schema["entities"][0]["properties"].append(
        {"name": "account_id", "type": "string"}
    )
    back = turtle_to_mapping(mapping_to_turtle(simple_bundle))
    assert _props(back, "Person") == ["name", "age", "account_id"]


def test_relationship_properties_lose_only_their_prefix(simple_bundle: MappingBundle) -> None:
    simple_bundle.conceptual_schema["relationships"][0]["properties"] = [
        {"name": "role_name", "type": "string"}
    ]
    back = turtle_to_mapping(mapping_to_turtle(simple_bundle))
    (rel,) = back.conceptual_schema["relationships"]
    assert [p["name"] for p in rel["properties"]] == ["role_name"]


def test_a_field_with_a_union_domain_belongs_to_every_member() -> None:
    bundle = turtle_to_mapping(ANALYZER_OWL)
    assert _props(bundle, "Chunk") == ["content"]
    assert _props(bundle, "Document") == ["content", "file_name", "page_count"]


def test_attribute_name_maps_the_property_to_its_stored_field() -> None:
    bundle = turtle_to_mapping(ANALYZER_OWL)
    assert bundle.physical_mapping["entities"]["Document"]["properties"] == {
        "file_name": {"field": "file-name"}
    }
    assert "properties" not in bundle.physical_mapping["entities"]["Chunk"]


def test_a_property_declared_once_per_domain_reaches_each(simple_bundle: MappingBundle) -> None:
    """mapping_to_turtle writes one block per entity for a shared name."""
    simple_bundle.conceptual_schema["entities"][1]["properties"].append({"name": "name", "type": "string"})
    back = turtle_to_mapping(mapping_to_turtle(simple_bundle))
    assert "name" in _props(back, "Person") and "name" in _props(back, "Movie")
