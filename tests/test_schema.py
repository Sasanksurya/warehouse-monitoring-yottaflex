import sqlite3

from whmon.schema import TABLES, TABLE_BY_NAME, ddl, data_dictionary_rows

ENTITIES = {"warehouse", "zone", "sensor", "sensor_reading", "door_event", "inventory_lot", "storage_requirement",
            "alarm", "inspection", "remediation"}


def test_all_required_entities_are_modelled():
    assert ENTITIES <= set(TABLE_BY_NAME)


def test_every_table_has_pk_and_fks_resolve():
    for t in TABLES:
        assert t.pk in t.names
        for f in t.fields:
            if f.fk:
                parent, col = f.fk.split(".")
                assert col in TABLE_BY_NAME[parent].names, f"{t.name}.{f.name} -> {f.fk}"


def test_bridge_tables_exist_for_many_to_many():
    for name in ("sensor_zone_assignment", "lot_zone_assignment", "alarm_lot_impact"):
        assert name in TABLE_BY_NAME


def test_every_field_is_documented_with_rule_columns():
    rows = list(data_dictionary_rows())
    assert len(rows) == sum(len(t.fields) for t in TABLES)
    assert all(r["type"] and r["required"] in ("yes", "no") for r in rows)


def test_ddl_is_valid_sqlite():
    con = sqlite3.connect(":memory:")
    con.executescript(ddl())
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert names == {t.name for t in TABLES}
