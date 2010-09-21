from ConfigParser import NoSectionError, NoOptionError, SafeConfigParser as ConfigParser

def run_all(methods, *args):
	for method in methods:
		method(*args)

def ignore():
	pass

class Option(object):
	def __init__(self, name):
		self.name = name
		self._value = None
		self._in_config_file = False
		self._on_update = []

	def update(self, parser, section_name):
		try:
			current_value = parser.get(section_name, self.name)
			self._in_config_file = True
			self.set(current_value)
		except (NoSectionError, NoOptionError):
			self._in_config_file = False
			self.set(None)

	def on_update(self, cb, eb=ignore, default=None, transform=str):
		self._on_update.append((cb, eb, default, transform))

	def set(self, value):
		if self._value == value:
			return
		self._value = value
		for cb, eb, default, transform in self._on_update:
			try:
				transformed = self.get(default, transform)
			except Exception, e:
				eb(e)
			else:
				cb(transformed)

	def get(self, default=None, transform=str):
		if self._value is None:
			return default
		return transform(self._value)
	
	@property
	def in_config_file(self):
		return self._in_config_file

	def __cmp__(self, other):
		return cmp(self.name, other.name)

	def __repr__(self):
		return "<Option %s>" % self.name

class Section(object):
	option_factory = Option

	def __init__(self, name):
		self.name = name
		self._options = {}
		self._in_config_file = False
		self._on_add = []
		self._on_remove = []

	def update(self, parser):
		#Get list of options in file before update
		options_in_file_before = set(self._iter_options_in_file())
		
		#Get list of options in file after update
		options_in_file_after = set()
		try:
			names = parser.options(self.name)
			self._in_config_file = True
			for name in names:
				option = self[name]
				options_in_file_after.add(option)
		except NoSectionError:
			self._in_config_file = False

		#Compare sets to figure out which options added/removed from file
		for option in options_in_file_after - options_in_file_before:
			run_all(self._on_add, option)

		for option in options_in_file_before - options_in_file_after:
			run_all(self._on_remove, option)

		#Look for updates in all option values
		for option in self:
			option.update(parser, self.name)
		

	def _iter_options_in_file(self):
		for option in self:
			if option.in_config_file:
				yield option

	def __getitem__(self, name):
		if name in self._options:
			return self._options[name]
		else:
			option = self.option_factory(name)
			self._options[name] = option
			return option

	def __iter__(self):
		return self._options.itervalues()

	def on_add(self, cb):
		self._on_add.append(cb)

	def on_remove(self, cb):
		self._on_remove.append(cb)

	@property
	def in_config_file(self):
		return self._in_config_file

	def __cmp__(self, other):
		return cmp(self.name, other.name)

	def __repr__(self):
		return "<Section %s>" % self.name

class ConfigFile(object):
	section_factory = Section

	def __init__(self, path):
		self.path = path
		self._sections = {}
		self._on_add = []
		self._on_remove = []
		self.update()

	def update(self):
		parser = ConfigParser()
		parser.read(self.path)

		#Get list of sections in file before update
		sections_in_file_before = set(self._iter_sections_in_file())
		
		#Get list of sections in file after update
		sections_in_file_after = set()
		try:
			names = parser.sections()
			self._in_config_file = True
			for name in names:
				section = self[name]
				sections_in_file_after.add(section)
		except NoSectionError:
			self._in_config_file = False
		
		#Compare sets to figure out which sections added/removed from file
		for section in sections_in_file_after - sections_in_file_before:
			run_all(self._on_add, section)

		for section in sections_in_file_before - sections_in_file_after:
			run_all(self._on_remove, section)

		#Look for updates in all section values
		for section in self:
			section.update(parser)

	def _iter_sections_in_file(self):
		for section in self:
			if section.in_config_file:
				yield section

	def __getitem__(self, name):
		if name in self._sections:
			return self._sections[name]
		else:
			section = self.section_factory(name)
			self._sections[name] = section
			return section
	
	def __iter__(self):
		return self._sections.itervalues()

	def on_add(self, cb):
		self._on_add.append(cb)

	def on_remove(self, cb):
		self._on_remove.append(cb)

	def __call__(self, section, option, default=None, transform=str, update_cb=None, update_eb=ignore):
		option = self[section][option]
		if update_cb is not None:
			option.on_update(update_cb, update_eb, default, transform)
		return option.get(default, transform) 

import unittest, tempfile, os

def make_test_config(bytes):
	fd, path = tempfile.mkstemp()
	fd = os.fdopen(fd, "w")
	fd.write(bytes)
	fd.flush()
	return ConfigFile(path), fd

def update_test_config(config, fd, bytes):
	fd.seek(0)
	fd.write(bytes)
	fd.flush()
	config.update()

def remove_test_config(config):
	os.unlink(config.path)

class TestConfigFile(unittest.TestCase):
	example_config1 = """
[foo]
a: 1
b: bar

[bar]
c: 14
d: 9

"""
	example_config2 = """
[bar]
c: 44
d: rawr

[baz]
e: hello
"""

	def setUp(self):
		self.cfgfd, self.cfgpath = tempfile.mkstemp()
		self.cfgfd = os.fdopen(self.cfgfd, "w")

	def _write_config(self, text):
		self.cfgfd.seek(0)
		self.cfgfd.write(text)
		self.cfgfd.flush()

	def tearDown(self):
		self.cfgfd.close()
		os.unlink(self.cfgpath)

	def test_call_basic(self):
		self._write_config(self.example_config1)
		config = ConfigFile(self.cfgpath)
		
		self.assertEquals(1, config('foo', 'a', transform=int, default=2))
		self.assertEquals("bar", config('foo', 'b', default=None))
		self.assertEquals(3, config('foo', 'c', transform=int, default=3))
		self.assertEquals(14, config('bar', 'c', transform=int, default=0))

		self._write_config(self.example_config2)
		config.update()

		self.assertEquals(2, config('foo', 'a', transform=int, default=2))
		self.assertEquals(None, config('foo', 'b', default=None))
		self.assertEquals(3, config('foo', 'c', transform=int, default=3))
		self.assertEquals(44, config('bar', 'c', transform=int, default=0))

	def test_call_cb(self):
		self._write_config(self.example_config1)
		config = ConfigFile(self.cfgpath)
		
		def cb(value):
			self._test_call_cb_result = value
		value = config('foo', 'a', transform=int, default=2, update_cb=cb)
		self.assertEquals(1, value)

		def eb(error):
			self._test_call_cb_error = error
		value = config('bar', 'd', transform=int, default=2, update_cb=lambda: None, update_eb=eb)
		self.assertEquals(9, value)

		self._write_config(self.example_config2)
		config.update()

		self.assertEquals(2, self._test_call_cb_result)
		self.assert_(isinstance(self._test_call_cb_error, ValueError))

	def test_section_add(self):
		self._write_config(self.example_config1)
		config = ConfigFile(self.cfgpath)

		def cb(section):
			self._test_section_add_name = section.name
		config.on_add(cb)

		self._write_config(self.example_config2)
		config.update()

		self.assertEquals('baz', self._test_section_add_name)

	def test_section_remove(self):
		self._write_config(self.example_config1)
		config = ConfigFile(self.cfgpath)

		def cb(section):
			self._test_section_remove_name = section.name
		config.on_remove(cb)

		self._write_config(self.example_config2)
		config.update()

		self.assertEquals('foo', self._test_section_remove_name)


if __name__ == "__main__":
	unittest.main()

