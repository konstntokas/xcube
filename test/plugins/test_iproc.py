import unittest

from xcube.util.ext import ExtensionRegistry


class InputProcessorPluginTest(unittest.TestCase):
    def test_init_plugin(self):
        from xcube.plugins.iproc import init_plugin
        ext_reg = ExtensionRegistry()
        init_plugin(ext_reg)
        self.assertTrue(ext_reg.has_ext('xcube.core.gen.iproc', 'default'))
