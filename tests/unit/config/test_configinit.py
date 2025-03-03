# vim: ft=python fileencoding=utf-8 sts=4 sw=4 et:
# Copyright 2017-2019 Florian Bruhin (The Compiler) <mail@qutebrowser.org>

# This file is part of qutebrowser.
#
# qutebrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# qutebrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with qutebrowser.  If not, see <http://www.gnu.org/licenses/>.

"""Tests for qutebrowser.config.configinit."""

import os
import sys
import logging
import unittest.mock

import pytest

from qutebrowser import qutebrowser
from qutebrowser.config import (config, configexc, configfiles, configinit,
                                configdata, configtypes)
from qutebrowser.utils import objreg, usertypes
from helpers import utils


@pytest.fixture
def init_patch(qapp, fake_save_manager, monkeypatch, config_tmpdir,
               data_tmpdir):
    monkeypatch.setattr(configfiles, 'state', None)
    monkeypatch.setattr(config, 'instance', None)
    monkeypatch.setattr(config, 'key_instance', None)
    monkeypatch.setattr(config, 'change_filters', [])
    monkeypatch.setattr(configinit, '_init_errors', None)
    monkeypatch.setattr(configtypes.Font, 'monospace_fonts', None)
    yield
    try:
        objreg.delete('config-commands')
    except KeyError:
        pass


@pytest.fixture
def args(fake_args):
    """Arguments needed for the config to init."""
    fake_args.temp_settings = []
    return fake_args


@pytest.fixture(autouse=True)
def configdata_init(monkeypatch):
    """Make sure configdata is init'ed and no test re-init's it."""
    if not configdata.DATA:
        configdata.init()
    monkeypatch.setattr(configdata, 'init', lambda: None)


class TestEarlyInit:

    def test_config_py_path(self, args, init_patch, config_py_arg):
        config_py_arg.write('c.colors.hints.bg = "red"\n')
        configinit.early_init(args)
        expected = 'colors.hints.bg = red'
        assert config.instance.dump_userconfig() == expected

    @pytest.mark.parametrize('config_py', [True, 'error', False])
    def test_config_py(self, init_patch, config_tmpdir, caplog, args,
                       config_py):
        """Test loading with only a config.py."""
        config_py_file = config_tmpdir / 'config.py'

        if config_py:
            config_py_lines = ['c.colors.hints.bg = "red"']
            if config_py == 'error':
                config_py_lines.append('c.foo = 42')
            config_py_file.write_text('\n'.join(config_py_lines),
                                      'utf-8', ensure=True)

        with caplog.at_level(logging.ERROR):
            configinit.early_init(args)

        # Check error messages
        expected_errors = []
        if config_py == 'error':
            expected_errors.append("While setting 'foo': No option 'foo'")

        if configinit._init_errors is None:
            actual_errors = []
        else:
            actual_errors = [str(err)
                             for err in configinit._init_errors.errors]

        assert actual_errors == expected_errors

        # Make sure things have been init'ed
        assert isinstance(config.instance, config.Config)
        assert isinstance(config.key_instance, config.KeyConfig)

        # Check config values
        if config_py:
            expected = 'colors.hints.bg = red'
        else:
            expected = '<Default configuration>'
        assert config.instance.dump_userconfig() == expected

    @pytest.mark.parametrize('load_autoconfig', [True, False])  # noqa
    @pytest.mark.parametrize('config_py', [True, 'error', False])
    @pytest.mark.parametrize('invalid_yaml', ['42', 'list', 'unknown',
                                              'wrong-type', False])
    def test_autoconfig_yml(self, init_patch, config_tmpdir, caplog, args,
                            load_autoconfig, config_py, invalid_yaml):
        """Test interaction between config.py and autoconfig.yml."""
        # Prepare files
        autoconfig_file = config_tmpdir / 'autoconfig.yml'
        config_py_file = config_tmpdir / 'config.py'

        yaml_lines = {
            '42': '42',
            'list': '[1, 2]',
            'unknown': [
                'settings:',
                '  colors.foobar:',
                '    global: magenta',
                'config_version: 2',
            ],
            'wrong-type': [
                'settings:',
                '  tabs.position:',
                '    global: true',
                'config_version: 2',
            ],
            False: [
                'settings:',
                '  colors.hints.fg:',
                '    global: magenta',
                'config_version: 2',
            ],
        }
        text = '\n'.join(yaml_lines[invalid_yaml])
        autoconfig_file.write_text(text, 'utf-8', ensure=True)

        if config_py:
            config_py_lines = ['c.colors.hints.bg = "red"']
            if load_autoconfig:
                config_py_lines.append('config.load_autoconfig()')
            if config_py == 'error':
                config_py_lines.append('c.foo = 42')
            config_py_file.write_text('\n'.join(config_py_lines),
                                      'utf-8', ensure=True)

        with caplog.at_level(logging.ERROR):
            configinit.early_init(args)

        # Check error messages
        expected_errors = []

        if load_autoconfig or not config_py:
            suffix = ' (autoconfig.yml)' if config_py else ''
            if invalid_yaml in ['42', 'list']:
                error = ("While loading data{}: Toplevel object is not a dict"
                         .format(suffix))
                expected_errors.append(error)
            elif invalid_yaml == 'wrong-type':
                error = ("Error{}: Invalid value 'True' - expected a value of "
                         "type str but got bool.".format(suffix))
                expected_errors.append(error)
            elif invalid_yaml == 'unknown':
                error = ("While loading options{}: Unknown option "
                         "colors.foobar".format(suffix))
                expected_errors.append(error)
        if config_py == 'error':
            expected_errors.append("While setting 'foo': No option 'foo'")

        if configinit._init_errors is None:
            actual_errors = []
        else:
            actual_errors = [str(err)
                             for err in configinit._init_errors.errors]

        assert actual_errors == expected_errors

        # Check config values
        dump = config.instance.dump_userconfig()

        if config_py and load_autoconfig and not invalid_yaml:
            expected = [
                'colors.hints.bg = red',
                'colors.hints.fg = magenta',
            ]
        elif config_py:
            expected = ['colors.hints.bg = red']
        elif invalid_yaml:
            expected = ['<Default configuration>']
        else:
            expected = ['colors.hints.fg = magenta']

        assert dump == '\n'.join(expected)

    def test_state_init_errors(self, init_patch, args, data_tmpdir):
        state_file = data_tmpdir / 'state'
        state_file.write_binary(b'\x00')
        configinit.early_init(args)
        assert configinit._init_errors.errors

    def test_invalid_change_filter(self, init_patch, args):
        config.change_filter('foobar')
        with pytest.raises(configexc.NoOptionError):
            configinit.early_init(args)

    def test_temp_settings_valid(self, init_patch, args):
        args.temp_settings = [('colors.completion.fg', 'magenta')]
        configinit.early_init(args)
        assert config.instance.get_obj('colors.completion.fg') == 'magenta'

    def test_temp_settings_invalid(self, caplog, init_patch, message_mock,
                                   args):
        """Invalid temp settings should show an error."""
        args.temp_settings = [('foo', 'bar')]

        with caplog.at_level(logging.ERROR):
            configinit.early_init(args)

        msg = message_mock.getmsg()
        assert msg.level == usertypes.MessageLevel.error
        assert msg.text == "set: NoOptionError - No option 'foo'"

    @pytest.mark.parametrize('settings, size, family', [
        # Only fonts.monospace customized
        ([('fonts.monospace', '"Comic Sans MS"')], 10, 'Comic Sans MS'),
        # fonts.monospace and font settings customized
        # https://github.com/qutebrowser/qutebrowser/issues/3096
        ([('fonts.monospace', '"Comic Sans MS"'),
          ('fonts.tabs', '12pt monospace'),
          ('fonts.keyhint', '12pt monospace')], 12, 'Comic Sans MS'),
    ])
    @pytest.mark.parametrize('method', ['temp', 'auto', 'py'])
    def test_monospace_fonts_init(self, init_patch, args, config_tmpdir,
                                  method, settings, size, family):
        """Ensure setting fonts.monospace at init works properly.

        See https://github.com/qutebrowser/qutebrowser/issues/2973
        """
        if method == 'temp':
            args.temp_settings = settings
        elif method == 'auto':
            autoconfig_file = config_tmpdir / 'autoconfig.yml'
            lines = (["config_version: 2", "settings:"] +
                     ["  {}:\n    global:\n      '{}'".format(k, v)
                      for k, v in settings])
            autoconfig_file.write_text('\n'.join(lines), 'utf-8', ensure=True)
        elif method == 'py':
            config_py_file = config_tmpdir / 'config.py'
            lines = ["c.{} = '{}'".format(k, v) for k, v in settings]
            config_py_file.write_text('\n'.join(lines), 'utf-8', ensure=True)

        configinit.early_init(args)

        # Font
        expected = '{}pt "{}"'.format(size, family)
        assert config.instance.get('fonts.keyhint') == expected
        # QtFont
        font = config.instance.get('fonts.tabs')
        assert font.pointSize() == size
        assert font.family() == family

    def test_monospace_fonts_later(self, init_patch, args):
        """Ensure setting fonts.monospace after init works properly.

        See https://github.com/qutebrowser/qutebrowser/issues/2973
        """
        configinit.early_init(args)
        changed_options = []
        config.instance.changed.connect(changed_options.append)

        config.instance.set_obj('fonts.monospace', '"Comic Sans MS"')

        assert 'fonts.keyhint' in changed_options  # Font
        assert config.instance.get('fonts.keyhint') == '10pt "Comic Sans MS"'
        assert 'fonts.tabs' in changed_options  # QtFont
        assert config.instance.get('fonts.tabs').family() == 'Comic Sans MS'

        # Font subclass, but doesn't end with "monospace"
        assert 'fonts.web.family.standard' not in changed_options

    def test_setting_monospace_fonts_family(self, init_patch, args):
        """Make sure setting fonts.monospace after a family works.

        See https://github.com/qutebrowser/qutebrowser/issues/3130
        """
        configinit.early_init(args)
        config.instance.set_str('fonts.web.family.standard', '')
        config.instance.set_str('fonts.monospace', 'Terminus')

    @pytest.mark.parametrize('config_opt, config_val, envvar, expected', [
        ('qt.force_software_rendering', 'software-opengl',
         'QT_XCB_FORCE_SOFTWARE_OPENGL', '1'),
        ('qt.force_software_rendering', 'qt-quick',
         'QT_QUICK_BACKEND', 'software'),
        ('qt.force_software_rendering', 'chromium',
         'QT_WEBENGINE_DISABLE_NOUVEAU_WORKAROUND', '1'),
        ('qt.force_platform', 'toaster', 'QT_QPA_PLATFORM', 'toaster'),
        ('qt.highdpi', True, 'QT_AUTO_SCREEN_SCALE_FACTOR', '1'),
        ('window.hide_decoration', True,
         'QT_WAYLAND_DISABLE_WINDOWDECORATION', '1')
    ])
    def test_env_vars(self, monkeypatch, config_stub,
                      config_opt, config_val, envvar, expected):
        """Check settings which set an environment variable."""
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)
        monkeypatch.setenv(envvar, '')  # to make sure it gets restored
        monkeypatch.delenv(envvar)

        config_stub.set_obj(config_opt, config_val)
        configinit._init_envvars()

        assert os.environ[envvar] == expected

    def test_env_vars_webkit(self, monkeypatch, config_stub):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebKit)
        configinit._init_envvars()


@pytest.mark.parametrize('errors', [True, 'fatal', False])
def test_late_init(init_patch, monkeypatch, fake_save_manager, args,
                   mocker, errors):
    configinit.early_init(args)

    if errors:
        err = configexc.ConfigErrorDesc("Error text", Exception("Exception"))
        errs = configexc.ConfigFileErrors("config.py", [err])
        if errors == 'fatal':
            errs.fatal = True

        monkeypatch.setattr(configinit, '_init_errors', errs)

    msgbox_mock = mocker.patch('qutebrowser.config.configinit.msgbox.msgbox',
                               autospec=True)
    exit_mock = mocker.patch('qutebrowser.config.configinit.sys.exit',
                             autospec=True)

    configinit.late_init(fake_save_manager)

    fake_save_manager.add_saveable.assert_any_call(
        'state-config', unittest.mock.ANY)
    fake_save_manager.add_saveable.assert_any_call(
        'yaml-config', unittest.mock.ANY, unittest.mock.ANY)

    if errors:
        assert len(msgbox_mock.call_args_list) == 1
        _call_posargs, call_kwargs = msgbox_mock.call_args_list[0]
        text = call_kwargs['text'].strip()
        assert text.startswith('Errors occurred while reading config.py:')
        assert '<b>Error text</b>: Exception' in text

        assert exit_mock.called == (errors == 'fatal')
    else:
        assert not msgbox_mock.called


class TestQtArgs:

    @pytest.fixture
    def parser(self, mocker):
        """Fixture to provide an argparser.

        Monkey-patches .exit() of the argparser so it doesn't exit on errors.
        """
        parser = qutebrowser.get_argparser()
        mocker.patch.object(parser, 'exit', side_effect=Exception)
        return parser

    @pytest.fixture(autouse=True)
    def reduce_args(self, monkeypatch, config_stub):
        """Make sure no --disable-shared-workers/referer argument get added."""
        monkeypatch.setattr(configinit.qtutils, 'version_check',
                            lambda version, compiled=False: True)
        config_stub.val.content.headers.referer = 'always'

    @pytest.mark.parametrize('args, expected', [
        # No Qt arguments
        (['--debug'], [sys.argv[0]]),
        # Qt flag
        (['--debug', '--qt-flag', 'reverse'], [sys.argv[0], '--reverse']),
        # Qt argument with value
        (['--qt-arg', 'stylesheet', 'foo'],
         [sys.argv[0], '--stylesheet', 'foo']),
        # --qt-arg given twice
        (['--qt-arg', 'stylesheet', 'foo', '--qt-arg', 'geometry', 'bar'],
         [sys.argv[0], '--stylesheet', 'foo', '--geometry', 'bar']),
        # --qt-flag given twice
        (['--qt-flag', 'foo', '--qt-flag', 'bar'],
         [sys.argv[0], '--foo', '--bar']),
    ])
    def test_qt_args(self, config_stub, args, expected, parser):
        """Test commandline with no Qt arguments given."""
        parsed = parser.parse_args(args)
        assert configinit.qt_args(parsed) == expected

    def test_qt_both(self, config_stub, parser):
        """Test commandline with a Qt argument and flag."""
        args = parser.parse_args(['--qt-arg', 'stylesheet', 'foobar',
                                  '--qt-flag', 'reverse'])
        qt_args = configinit.qt_args(args)
        assert qt_args[0] == sys.argv[0]
        assert '--reverse' in qt_args
        assert '--stylesheet' in qt_args
        assert 'foobar' in qt_args

    def test_with_settings(self, config_stub, parser):
        parsed = parser.parse_args(['--qt-flag', 'foo'])
        config_stub.val.qt.args = ['bar']
        assert configinit.qt_args(parsed) == [sys.argv[0], '--foo', '--bar']

    @pytest.mark.parametrize('backend, expected', [
        (usertypes.Backend.QtWebEngine, True),
        (usertypes.Backend.QtWebKit, False),
    ])
    def test_shared_workers(self, config_stub, monkeypatch, parser,
                            backend, expected):
        monkeypatch.setattr(configinit.qtutils, 'version_check',
                            lambda version, compiled=False: False)
        monkeypatch.setattr(configinit.objects, 'backend', backend)
        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)
        assert ('--disable-shared-workers' in args) == expected

    @pytest.mark.parametrize('backend, version_check, debug_flag, expected', [
        # Qt >= 5.12.3: Enable with -D stack, do nothing without it.
        (usertypes.Backend.QtWebEngine, True, True, True),
        (usertypes.Backend.QtWebEngine, True, False, None),
        # Qt < 5.12.3: Do nothing with -D stack, disable without it.
        (usertypes.Backend.QtWebEngine, False, True, None),
        (usertypes.Backend.QtWebEngine, False, False, False),
        # QtWebKit: Do nothing
        (usertypes.Backend.QtWebKit, True, True, None),
        (usertypes.Backend.QtWebKit, True, False, None),
        (usertypes.Backend.QtWebKit, False, True, None),
        (usertypes.Backend.QtWebKit, False, False, None),
    ])
    def test_in_process_stack_traces(self, monkeypatch, parser, backend,
                                     version_check, debug_flag, expected):
        monkeypatch.setattr(configinit.qtutils, 'version_check',
                            lambda version, compiled=False: version_check)
        monkeypatch.setattr(configinit.objects, 'backend', backend)
        parsed = parser.parse_args(['--debug-flag', 'stack'] if debug_flag
                                   else [])
        args = configinit.qt_args(parsed)

        if expected is None:
            assert '--disable-in-process-stack-traces' not in args
            assert '--enable-in-process-stack-traces' not in args
        elif expected:
            assert '--disable-in-process-stack-traces' not in args
            assert '--enable-in-process-stack-traces' in args
        else:
            assert '--disable-in-process-stack-traces' in args
            assert '--enable-in-process-stack-traces' not in args

    @pytest.mark.parametrize('flags, expected', [
        ([], []),
        (['--debug-flag', 'chromium'], ['--enable-logging', '--v=1']),
    ])
    def test_chromium_debug(self, monkeypatch, parser, flags, expected):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)
        parsed = parser.parse_args(flags)
        assert configinit.qt_args(parsed) == [sys.argv[0]] + expected

    def test_disable_gpu(self, config_stub, monkeypatch, parser):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)
        config_stub.val.qt.force_software_rendering = 'chromium'
        parsed = parser.parse_args([])
        expected = [sys.argv[0], '--disable-gpu']
        assert configinit.qt_args(parsed) == expected

    @utils.qt510
    @pytest.mark.parametrize('new_version, autoplay, added', [
        (True, False, False),  # new enough to not need it
        (False, True, False),  # autoplay enabled
        (False, False, True),
    ])
    def test_autoplay(self, config_stub, monkeypatch, parser,
                      new_version, autoplay, added):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)
        config_stub.val.content.autoplay = autoplay
        monkeypatch.setattr(configinit.qtutils, 'version_check',
                            lambda version, compiled=False: new_version)

        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)
        assert ('--autoplay-policy=user-gesture-required' in args) == added

    @utils.qt59
    @pytest.mark.parametrize('policy, arg', [
        ('all-interfaces', None),

        ('default-public-and-private-interfaces',
         '--force-webrtc-ip-handling-policy='
         'default_public_and_private_interfaces'),

        ('default-public-interface-only',
         '--force-webrtc-ip-handling-policy='
         'default_public_interface_only'),

        ('disable-non-proxied-udp',
         '--force-webrtc-ip-handling-policy='
         'disable_non_proxied_udp'),
    ])
    def test_webrtc(self, config_stub, monkeypatch, parser,
                    policy, arg):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)
        config_stub.val.content.webrtc_ip_handling_policy = policy

        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)

        if arg is None:
            assert not any(a.startswith('--force-webrtc-ip-handling-policy=')
                           for a in args)
        else:
            assert arg in args

    @pytest.mark.parametrize('canvas_reading, added', [
        (True, False),  # canvas reading enabled
        (False, True),
    ])
    def test_canvas_reading(self, config_stub, monkeypatch, parser,
                            canvas_reading, added):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)

        config_stub.val.content.canvas_reading = canvas_reading
        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)
        assert ('--disable-reading-from-canvas' in args) == added

    @pytest.mark.parametrize('process_model, added', [
        ('process-per-site-instance', False),
        ('process-per-site', True),
        ('single-process', True),
    ])
    def test_process_model(self, config_stub, monkeypatch, parser,
                           process_model, added):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)

        config_stub.val.qt.process_model = process_model
        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)

        if added:
            assert '--' + process_model in args
        else:
            assert '--process-per-site' not in args
            assert '--single-process' not in args
            assert '--process-per-site-instance' not in args
            assert '--process-per-tab' not in args

    @pytest.mark.parametrize('low_end_device_mode, arg', [
        ('auto', None),
        ('always', '--enable-low-end-device-mode'),
        ('never', '--disable-low-end-device-mode'),
    ])
    def test_low_end_device_mode(self, config_stub, monkeypatch, parser,
                                 low_end_device_mode, arg):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)

        config_stub.val.qt.low_end_device_mode = low_end_device_mode
        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)

        if arg is None:
            assert '--enable-low-end-device-mode' not in args
            assert '--disable-low-end-device-mode' not in args
        else:
            assert arg in args

    @pytest.mark.parametrize('referer, arg', [
        ('always', None),
        ('never', '--no-referrers'),
        ('same-domain', '--reduced-referrer-granularity'),
    ])
    def test_referer(self, config_stub, monkeypatch, parser, referer, arg):
        monkeypatch.setattr(configinit.objects, 'backend',
                            usertypes.Backend.QtWebEngine)

        config_stub.val.content.headers.referer = referer
        parsed = parser.parse_args([])
        args = configinit.qt_args(parsed)

        if arg is None:
            assert '--no-referrers' not in args
            assert '--reduced-referrer-granularity' not in args
        else:
            assert arg in args


@pytest.mark.parametrize('arg, confval, used', [
    # overridden by commandline arg
    ('webkit', 'webengine', usertypes.Backend.QtWebKit),
    # set in  config
    (None, 'webkit', usertypes.Backend.QtWebKit),
])
def test_get_backend(monkeypatch, args, config_stub,
                     arg, confval, used):
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name != 'PyQt5.QtWebKit':
            return real_import(name, *args, **kwargs)
        raise ImportError

    args.backend = arg
    config_stub.val.backend = confval
    monkeypatch.setattr('builtins.__import__', fake_import)

    assert configinit.get_backend(args) == used
