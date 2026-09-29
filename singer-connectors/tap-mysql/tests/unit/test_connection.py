import unittest

from unittest.mock import patch, MagicMock, call

import pymysql
from pymysql.cursors import Cursor
from singer import CatalogEntry

from tap_mysql.connection import (
    DEFAULT_SESSION_SQLS,
    ERR_UNKNOWN_SYSTEM_VARIABLE,
    MYSQL_MAX_EXECUTION_TIME_SQL,
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

    def _run_session_sqls_with_execute_side_effect(self, side_effect):
        mysql_con = MagicMock(spec_set=MySQLConnection).return_value
        mysql_con.session_sqls = DEFAULT_SESSION_SQLS
        cur_mock = MagicMock(spec_set=Cursor).return_value
        cur_mock.__enter__.return_value.execute.side_effect = side_effect
        mysql_con.cursor.return_value = cur_mock
        run_session_sqls(mysql_con)

    def test_unsupported_max_execution_time_is_a_soft_warning(self):
        # Simon-Data fix (ported from transferwise/pipelinewise#1365):
        # max_execution_time isn't guaranteed on every MySQL-compatible
        # engine we might point this tap at -- failing to set it shouldn't
        # crash the whole connection.
        def execute(sql, *args):
            if sql == MYSQL_MAX_EXECUTION_TIME_SQL:
                raise pymysql.err.OperationalError(ERR_UNKNOWN_SYSTEM_VARIABLE, 'Unknown system variable')

        self._run_session_sqls_with_execute_side_effect(execute)  # does not raise

    def test_other_operational_error_on_max_execution_time_still_raises(self):
        # Only the specific "unsupported variable" error is swallowed --
        # e.g. a connection genuinely dropped while setting it should not be.
        def execute(sql, *args):
            if sql == MYSQL_MAX_EXECUTION_TIME_SQL:
                raise pymysql.err.OperationalError(2013, 'Lost connection to MySQL server during query')

        with self.assertRaises(pymysql.err.OperationalError):
            self._run_session_sqls_with_execute_side_effect(execute)

    def test_unsupported_variable_error_on_non_optional_sql_still_raises(self):
        # The fallback is scoped to MYSQL_MAX_EXECUTION_TIME_SQL specifically,
        # not every session SQL -- a mandatory one failing should still crash.
        def execute(sql, *args):
            if sql == 'SET @@session.net_write_timeout=3600':
                raise pymysql.err.OperationalError(ERR_UNKNOWN_SYSTEM_VARIABLE, 'Unknown system variable')

        with self.assertRaises(pymysql.err.OperationalError):
            self._run_session_sqls_with_execute_side_effect(execute)
