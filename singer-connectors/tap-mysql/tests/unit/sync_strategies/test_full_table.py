from unittest import TestCase
from unittest.mock import MagicMock, patch

import pymysql
from singer import Schema
from singer.catalog import CatalogEntry

from tap_mysql.sync_strategies import full_table


def _make_catalog_entry():
    return CatalogEntry(
        tap_stream_id='test_db-test_table',
        stream='test_table',
        table='test_table',
        schema=Schema(properties={'id': Schema(type=['integer'])}),
        metadata=[
            {'breadcrumb': (),
             'metadata': {'database-name': 'test_db',
                          'table-key-properties': ['id'],
                          'replication-method': 'FULL_TABLE'}},
        ],
    )


class TestFullTableReconnectRetry(TestCase):
    """
    Simon-Data fix: a connection dropped mid-snapshot (pymysql 2006/2013) used
    to kill the whole tap run. sync_table() now retries by reconnecting and
    resuming from the 'last_pk_fetched' bookmark that common.sync_query()
    already maintains per-row.
    """

    def setUp(self):
        self.catalog_entry = _make_catalog_entry()
        self.state = {}
        self.mysql_conn = MagicMock()

        pks_patch = patch(
            'tap_mysql.sync_strategies.full_table.pks_are_auto_incrementing',
            return_value=False,
        )
        pks_patch.start()
        self.addCleanup(pks_patch.stop)

        connect_patch = patch('tap_mysql.sync_strategies.full_table.open_connection')
        connect_mock = connect_patch.start()
        self.addCleanup(connect_patch.stop)
        open_conn = MagicMock()
        connect_mock.return_value.__enter__.return_value = open_conn
        self.cursor_cm = open_conn.cursor.return_value
        self.cursor_cm.__enter__.return_value = MagicMock()

        sync_query_patch = patch('tap_mysql.sync_strategies.common.sync_query')
        self.sync_query_mock = sync_query_patch.start()
        self.addCleanup(sync_query_patch.stop)

        write_message_patch = patch('tap_mysql.sync_strategies.full_table.singer.write_message')
        write_message_patch.start()
        self.addCleanup(write_message_patch.stop)

    def _sync(self):
        full_table.sync_table(self.mysql_conn, self.catalog_entry, self.state, ['id'], 123)

    def test_retries_and_succeeds_after_reconnectable_error(self):
        lost_connection = pymysql.err.OperationalError(2013, 'Lost connection to MySQL server during query')
        self.sync_query_mock.side_effect = [lost_connection, None]

        self._sync()

        self.assertEqual(self.sync_query_mock.call_count, 2)

    def test_masked_error_via_cursor_cleanup_is_still_retried_from_root_cause(self):
        # Reproduces the actual production failure: pymysql's own cursor.close()
        # (invoked by `with cursor() as cur:`'s __exit__) raises AttributeError
        # trying to finish an unbuffered query on an already-dead socket, which
        # supersedes the original OperationalError via Python's implicit
        # exception chaining ("During handling of the above exception...").
        lost_connection = pymysql.err.OperationalError(2013, 'Lost connection to MySQL server during query')
        self.sync_query_mock.side_effect = [lost_connection, None]
        self.cursor_cm.__exit__.side_effect = [
            AttributeError("'NoneType' object has no attribute 'settimeout'"),
            False,
        ]

        self._sync()

        self.assertEqual(self.sync_query_mock.call_count, 2)

    def test_server_gone_away_is_also_retried(self):
        gone_away = pymysql.err.OperationalError(2006, 'MySQL server has gone away')
        self.sync_query_mock.side_effect = [gone_away, None]

        self._sync()

        self.assertEqual(self.sync_query_mock.call_count, 2)

    def test_gives_up_after_max_attempts(self):
        lost_connection = pymysql.err.OperationalError(2013, 'Lost connection to MySQL server during query')
        self.sync_query_mock.side_effect = lost_connection

        with self.assertRaises(pymysql.err.OperationalError):
            self._sync()

        self.assertEqual(self.sync_query_mock.call_count, full_table.MAX_RECONNECT_ATTEMPTS)

    def test_non_reconnectable_operational_error_is_not_retried(self):
        access_denied = pymysql.err.OperationalError(1045, 'Access denied')
        self.sync_query_mock.side_effect = access_denied

        with self.assertRaises(pymysql.err.OperationalError):
            self._sync()

        self.assertEqual(self.sync_query_mock.call_count, 1)

    def test_non_operational_error_is_not_retried(self):
        self.sync_query_mock.side_effect = ValueError('boom')

        with self.assertRaises(ValueError):
            self._sync()

        self.assertEqual(self.sync_query_mock.call_count, 1)
