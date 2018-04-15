import os
import pytest
from buildstream import _yaml
from buildstream._exceptions import ErrorDomain, LoadErrorReason
from tests.testutils.runcli import cli


# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "variables"
)


###############################################################
#  Test proper loading of some default commands from plugins  #
###############################################################
@pytest.mark.parametrize("target,varname,expected", [
    ('autotools.bst', 'make-install', "make -j1 DESTDIR=\"/buildstream-install\" install"),
    ('cmake.bst', 'cmake',
     "cmake -B_builddir -H. -G\"Unix Makefiles\" -DCMAKE_INSTALL_PREFIX:PATH=\"/usr\" \\\n" +
     "-DCMAKE_INSTALL_LIBDIR=lib   "),
    ('distutils.bst', 'python-install',
     "python3 setup.py install --prefix \"/usr\" \\\n" +
     "--root \"/buildstream-install\""),
    ('makemaker.bst', 'configure', "perl Makefile.PL PREFIX=/buildstream-install/usr"),
    ('modulebuild.bst', 'configure', "perl Build.PL --prefix \"/buildstream-install/usr\""),
    ('qmake.bst', 'make-install', "make -j1 INSTALL_ROOT=\"/buildstream-install\" install"),
])
@pytest.mark.datafiles(os.path.join(DATA_DIR, 'defaults'))
def test_defaults(cli, datafiles, tmpdir, target, varname, expected):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    result = cli.run(project=project, silent=True, args=[
        'show', '--deps', 'none', '--format', '%{vars}', target
    ])
    result.assert_success()
    result_vars = _yaml.load_data(result.output)
    assert result_vars[varname] == expected


################################################################
#  Test overriding of variables to produce different commands  #
################################################################
@pytest.mark.parametrize("target,varname,expected", [
    ('autotools.bst', 'make-install', "make -j1 DESTDIR=\"/custom/install/root\" install"),
    ('cmake.bst', 'cmake',
     "cmake -B_builddir -H. -G\"Ninja\" -DCMAKE_INSTALL_PREFIX:PATH=\"/opt\" \\\n" +
     "-DCMAKE_INSTALL_LIBDIR=lib   "),
    ('distutils.bst', 'python-install',
     "python3 setup.py install --prefix \"/opt\" \\\n" +
     "--root \"/custom/install/root\""),
    ('makemaker.bst', 'configure', "perl Makefile.PL PREFIX=/custom/install/root/opt"),
    ('modulebuild.bst', 'configure', "perl Build.PL --prefix \"/custom/install/root/opt\""),
    ('qmake.bst', 'make-install', "make -j1 INSTALL_ROOT=\"/custom/install/root\" install"),
])
@pytest.mark.datafiles(os.path.join(DATA_DIR, 'overrides'))
def test_overrides(cli, datafiles, tmpdir, target, varname, expected):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    result = cli.run(project=project, silent=True, args=[
        'show', '--deps', 'none', '--format', '%{vars}', target
    ])
    result.assert_success()
    result_vars = _yaml.load_data(result.output)
    assert result_vars[varname] == expected