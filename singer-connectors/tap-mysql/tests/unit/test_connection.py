import unittest

from unittest.mock import patch, MagicMock, call

from pymysql.cursors import Cursor
from singer import CatalogEntry

from tap_mysql.connection import (
    DEFAULT_SESSION_SQLS,
    READ_TIMEOUT_SECONDS,
    MySQLConnection,
    fetch_server_id,
    fetch_server_uuid,
    run_session_sqls,
)

import tap_mysql.connection


class TestConnection(unittest.TestCase):

    @patch('tap_mysql.connection.connect_with_backoff')
    def test_fetch_server_id(self, connect_with_backoff):

        mysql_con = MagicMock(spec_set=MySQLConnection).return_value
        cur_mock = MagicMock(spec_set=Cursor).return_value
        cur_mock.__enter__.return_value.fetchone.return_value = [111]

        mysql_con.__enter__.return_value.cursor.return_value = cur_mock

        connect_with_backoff.return_value = mysql_con

        result = fetch_server_id(mysql_con)

        self.assertEqual(111, result)

        connect_with_backoff.assert_called_with(mysql_con)

        cur_mock.__enter__.return_value.execute.assert_has_calls(
            [
                call('SELECT @@server_id'),
            ]
        )

    @patch('tap_mysql.connection.connect_with_backoff')
    def test_fetch_server_uuid(self, connect_with_backoff):

        mysql_con = MagicMock(spec_set=MySQLConnection).return_value
        cur_mock = MagicMock(spec_set=Cursor).return_value
        cur_mock.__enter__.return_value.fetchone.return_value = ['dkfhdsf0-ejr-dfbsf-dnfnsbdmfbdf']

        mysql_con.__enter__.return_value.cursor.return_value = cur_mock

        connect_with_backoff.return_value = mysql_con

        result = fetch_server_uuid(mysql_con)

        self.assertEqual('dkfhdsf0-ejr-dfbsf-dnfnsbdmfbdf', result)

        connect_with_backoff.assert_called_with(mysql_con)

        cur_mock.__enter__.return_value.execute.assert_has_calls(
            [
                call('SELECT @@server_uuid'),
            ]
        )

    def test_default_session_sqls_sets_net_write_timeout_and_max_execution_time(self):
        # Simon-Data fix: net_write_timeout was previously left at the
        # server's own default (commonly 60s), killing unbuffered
        # full-table scans with `Lost connection to MySQL server during
        # query` on any table that took a while to stream.
        self.assertIn('SET @@session.net_write_timeout=3600', DEFAULT_SESSION_SQLS)
        self.assertIn('SET @@session.max_execution_time=0', DEFAULT_SESSION_SQLS)

    def test_connection_sets_a_real_client_side_read_timeout(self):
        # Simon-Data fix: `net_read_timeout` is a session SQL var that only
        # bounds the *server's* patience waiting on us -- it does nothing for
        # our own socket read, which pymysql leaves unbounded (blocks
        # forever) unless `read_timeout` is passed as a connection arg.
        conn = MySQLConnection({'user': 'u', 'password': 'p', 'host': 'h', 'port': '3306'})
        self.assertEqual(conn._read_timeout, READ_TIMEOUT_SECONDS)

    def test_run_session_sqls_executes_every_default_session_sql(self):
        mysql_con = MagicMock(spec_set=MySQLConnection).return_value
        mysql_con.session_sqls = DEFAULT_SESSION_SQLS
        cur_mock = MagicMock(spec_set=Cursor).return_value
        mysql_con.cursor.return_value = cur_mock

        run_session_sqls(mysql_con)

        cur_mock.__enter__.return_value.execute.assert_has_calls(
            [call(sql) for sql in DEFAULT_SESSION_SQLS]
        )
