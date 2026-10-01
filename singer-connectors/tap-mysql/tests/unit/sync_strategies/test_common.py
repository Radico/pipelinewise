import datetime

from singer.catalog import CatalogEntry
from singer.schema import Schema

from tap_mysql.sync_strategies import common


class TestCommonSyncStrategyHelpers:

    def test_row_to_singer_record(self):
        catalog_entry = CatalogEntry(
            stream='stream',
            schema=Schema.from_dict({
                'type': 'object',
                'properties': {
                    'time': {
                        'type': 'string',
                        'format': 'time',
                    },
                },
            }),
        )
        message = common.row_to_singer_record(
            catalog_entry,
            version=1,
            row=(datetime.timedelta(hours=8, minutes=30),),
            columns=['time'],
            time_extracted=datetime.datetime.now(datetime.timezone.utc),
        )

        assert message.stream == 'stream'
        assert message.version == 1
        assert message.record == {'time': '08:30:00'}
        assert message.time_extracted is not None

    def test_row_to_singer_record_parses_json_columns_into_objects(self):
        catalog_entry = CatalogEntry(
            stream='stream',
            schema=Schema.from_dict({
                'type': 'object',
                'properties': {
                    'attrs': {'type': ['null', 'object']},
                },
            }),
        )

        def record_for(value):
            return common.row_to_singer_record(
                catalog_entry,
                version=1,
                row=(value,),
                columns=['attrs'],
                time_extracted=datetime.datetime.now(datetime.timezone.utc),
            ).record

        assert record_for('{}') == {'attrs': {}}
        assert record_for('{"a": [1, 2], "b": {"c": null}}') == {'attrs': {'a': [1, 2], 'b': {'c': None}}}
        assert record_for(b'{"a": 1}') == {'attrs': {'a': 1}}
        assert record_for(None) == {'attrs': None}
        assert record_for({'a': 1}) == {'attrs': {'a': 1}}

    def test_row_to_singer_record_leaves_string_columns_untouched(self):
        catalog_entry = CatalogEntry(
            stream='stream',
            schema=Schema.from_dict({
                'type': 'object',
                'properties': {
                    'name': {'type': ['null', 'string']},
                },
            }),
        )
        message = common.row_to_singer_record(
            catalog_entry,
            version=1,
            row=('{}',),
            columns=['name'],
            time_extracted=datetime.datetime.now(datetime.timezone.utc),
        )

        assert message.record == {'name': '{}'}

