import os, os.path, logging, logging.handlers, signal, sys, time, optparse, pwd, grp, errno, traceback
import config

class DaemonStopped(Exception):
	def __init__(self):
		Exception.__init__(self, "Daemon is not running")

class DaemonRunning(Exception):
	def __init__(self):
		Exception.__init__(self, "Daemon is running")

class Daemon(object):
	"""A daemon with start/stop/etc, pidfile, and logging support.

	Daemon config should exist in /etc/<daemon_name>.conf
	[daemon]
	user: <user_name_to_run_as>
	group: <group_name_to_run_as>
	umask: <octal umask>

	[logging]
	level: <debug|info|warning>
	format: <see python logging module>
	syslog_host: <host to syslog to>
	syslog_port: <port to syslog to>
	"""
	SYSTEM_CONFIG_BASE = "/etc"
	SYSTEM_READONLY_BASE = "/usr"
	SYSTEM_DATA_BASE = "/var"

	name = "unknown_daemon"
	description = ""

	should_daemonize = True
	signal_alias = {}

	def __init__(self):
		self.config = config.ConfigFile(self.config_path)
		self._setup_logging()

	# PATHS

	@property
	def sys_runtime_path(self):
		"""System runtime data path"""
		return os.path.join(self.SYSTEM_DATA_BASE, "run")

	@property
	def sys_state_path(self):
		"""System state data path"""
		return os.path.join(self.SYSTEM_DATA_BASE, "lib")

	@property
	def sys_lock_path(self):
		"""System lock file path"""
		return os.path.join(self.SYSTEM_DATA_BASE, "lock")

	@property
	def sys_cache_path(self):
		"""System cache data path"""
		return os.path.join(self.SYSTEM_DATA_BASE, "cache")
	
	@property
	def sys_bin_path(self):
		"""System executable path"""
		return os.path.join(self.SYSTEM_READONLY_BASE, "bin")

	@property
	def sys_lib_path(self):
		"""System architecture-dependent data"""
		return os.path.join(self.SYSTEM_READONLY_BASE, "lib")

	@property
	def sys_share_path(self):
		"""System architecture-independent data"""
		return os.path.join(self.SYSTEM_READONLY_BASE, "share")

	@property
	def pidfile_dir(self):
		"""Process pidfile directory
		Required for processes that drop permissions"""
		return os.path.join(self.sys_runtime_path, self.name)

	@property
	def pidfile_path(self):
		"""Process pidfile path"""
		return os.path.join(self.pidfile_dir, "%s.pid" % self.name)

	@property
	def pid(self):
		"""The value of the daemon process's pidfile"""
		try:
			return int(open(self.pidfile_path).read())
		except IOError, e:
			if e.args[0] == errno.ENOENT:
				raise DaemonStopped()
			else:
				raise

	@property
	def config_path(self):
		"""Daemon configuration file path"""
		return os.path.join(self.SYSTEM_CONFIG_BASE, "%s.conf" % self.name)

	@property
	def config_dir_path(self):
		"""Daemon configuration directory path"""
		return os.path.join(self.SYSTEM_CONFIG_BASE, "%s" % self.name)

	# DAEMON HELPERS

	def daemonize(self):
		"""Call the given callback in a new daemonized child process"""
		self._prepare_daemon()
		self._load_privileges()
		self._make_pidfile_dir()
		
		# Fork child process (unless we run in foreground)
		try:
			if self.should_daemonize:
				first_fork_retval = os.fork()
				if first_fork_retval > 0:
					return
				os.setsid()
				self._setup_std_pipes()
				second_fork_retval = os.fork()
				if second_fork_retval > 0:
					sys.exit(0)
		except SystemExit:
			raise
		except Exception, e:
			self.logger.error("Failed to fork daemon process")
			self.logger.exception(e)
			raise SystemExit(1)
		
		# Run daemon
		try:
			try:
				self.logger.info("Started")
				self.handle_prerun()
				self._drop_privileges()
				self._write_pidfile()
				self._setup_signal_handlers()
				self.handle_run()
				self.logger.info("Stopped")
			finally:
				try:
					self._remove_pidfile()
				except Exception, e:
					self.logger.warning("Could not remove pidfile")
					self.logger.exception(e)
		except SystemExit, e:
			errcode = e.args[0]
			if errcode == 0:
				self.logger.info("Stopped")
			else:
				self.logger.warning("Stopped with code %d" % e.args[0])
			raise
		except Exception, e:
			self.logger.error("Killed by uncaught exception")
			self.logger.exception(e)
			raise SystemExit(1)

	def _prepare_daemon(self):
		umask = self.config("daemon", "umask", 0007, transform=lambda x: int(x, 8))
		os.umask(umask)
		os.chdir("/")

	def _setup_std_pipes(self):
		devnull = open("/dev/null", "r+")
		for pipe in [sys.stdin, sys.stdout, sys.stderr]:
			pipe.flush()
			os.dup2(devnull.fileno(), pipe.fileno())

	def _make_pidfile_dir(self):
		if not os.path.exists(self.pidfile_dir):
			os.mkdir(self.pidfile_dir, 0770)
		os.lchown(self.pidfile_dir, self._use_uid, self._use_gid)

	def _write_pidfile(self):
		f = open(self.pidfile_path, "w")
		f.write(str(os.getpid()))

	def _remove_pidfile(self):
		os.unlink(self.pidfile_path)

	def _setup_signal_handlers(self):
		signal.signal(signal.SIGINT, lambda *_: self.handle_stop())
		signal.signal(signal.SIGTERM, lambda *_: self.handle_stop())
		signal.signal(signal.SIGHUP, lambda *_: self.handle_update())
		signal.signal(signal.SIGUSR1, lambda *_: self.handle_usr1())
		signal.signal(signal.SIGUSR2, lambda *_: self.handle_usr2())

	def _load_privileges(self):
		username  = self.config("daemon", "user", "root")
		groupname = self.config("daemon", "group", "root")
		userentry  = pwd.getpwnam(username)
		groupentry = grp.getgrnam(groupname)
		self._use_uid = userentry.pw_uid
		self._use_gid = groupentry.gr_gid

	def _drop_privileges(self):
		os.setgid(self._use_gid)
		os.setuid(self._use_uid)

	def _setup_logging(self):
		logger = logging.getLogger()

		level_names = {
				"critical" : logging.CRITICAL,
				"error" : logging.ERROR,
				"warning" : logging.WARNING,
				"info" : logging.INFO,
				"debug" : logging.DEBUG
				}
		level = self.config("logging", "level", "info")
		logger.setLevel(level_names[level.lower()])
		
		log_format = self.config("logging", "format", "%(name)s: %(message)s")
		formatter = logging.Formatter(log_format)
		
		syslog_host = self.config("logging", "syslog_host", "")
		syslog_port = self.config("logging", "syslog_port", 514)
		syslog_address = syslog_host and (syslog_host, syslog_port) or "/dev/log"
		syslog_handler = logging.handlers.SysLogHandler(syslog_address, logging.handlers.SysLogHandler.LOG_DAEMON)
		syslog_handler.setFormatter(formatter)
		logger.addHandler(syslog_handler)
		
		stream_handler = logging.StreamHandler()
		stream_handler.setFormatter(formatter)
		logger.addHandler(stream_handler)
		
		self.logger = logging.getLogger(self.name)

	# PROCESS CONTROL

	def start(self):
		"""Fork and run a new daemon process."""
		if self.status:
			raise DaemonRunning()
		self.daemonize()

	def foreground(self):
		"""Run the process in the foreground."""
		self.should_daemonize = False
		self.start()

	def stop(self, kill_after=None):
		"""Stop the daemon process or kill it if it won't stop.
		@param kill_after Seconds to wait until we kill the process, None means we never kill it"""
		self.signal(signal.SIGTERM)
		
		#All done!
		if kill_after is None:
			return

		#Poll the process status and kill it if it doesn't stop
		elapsed = 0
		increment = 0.25
		while elapsed < kill_after:
			if self.status is False:
				return
			time.sleep(increment)
			elapsed += increment
		self.kill()

	def kill(self):
		"""Kill the process.
		Kills the process with no notice and no chance to continue."""
		self.logger.warning("User sent kill signal. You may need to clean up things like the pidfile.")
		self.signal(signal.SIGKILL)

	def restart(self, kill_after=None):
		"""Restart the process."""
		if self.status:
			self.stop(kill_after)
		self.start()

	def update(self):
		"""Tell the process to update itself."""
		self.signal(signal.SIGHUP)
	
	@property
	def status(self):
		"""Check if the daemon process is running.
		@return True if running"""
		try:
			self.signal(0)
			return True
		except OSError:
			self.logger.warning("Pidfile exists but no process is running with pid %s" % self.pid)
			return False
		except DaemonStopped:
			return False

	def signal(self, signum):
		"""Send a signal to the daemon process."""
		try:
			os.kill(self.pid, signum)
		except OSError, e:
			if e.args[0] == errno.ESRCH:
				raise DaemonStopped()
			else:
				raise

	# CHILD IMPLEMENTATION

	def handle_prerun(self):
		"""Prepare for handle_run after fork as a privileged user.
		Example: Open a server socket on a privileged port, then drop to an unprivileged user
		"""
		pass

	def handle_run(self):
		"""Daemon's main loop."""
		raise NotImplementedError()

	def handle_stop(self):
		"""Handle a stop/sigterm"""
		raise SystemExit(0)

	def handle_update(self):
		"""Handle an update/sighup.
		This function is called in an interrupt, watchout for deadlock!
		Default action is to call self.reload_config()"""
		self.logger.info("Reloading config")
		self.config.update()

	def handle_usr1(self):
		pass

	def handle_usr2(self):
		pass

def _make_killer(daemon, signum):
	return lambda: daemon.signal(signum)

def make_main(daemon_type, stop_wait_time=8):
	"""Create a main function for a given daemon type.
	@param daemon_type The daemon object factory/class
	@param stop_wait_time Seconds to wait until killing a process"""
	def main():
		daemon = daemon_type()
		extra_cmds = "".join(map(lambda x: ("|" + x), daemon.signal_alias.values()))

		usage = "%prog <start|stop|kill|restart|update|status|foreground" + extra_cmds + ">"
		parser = optparse.OptionParser(usage=usage, description=daemon_type.description)
		parser.add_option("-d", "--debug", dest="debug", action="store_true", help="Print full tracebacks", default=False)
		
		options, args = parser.parse_args()

		if len(args) != 1:
			parser.error("Exactly one argument required")
		action = args[0]


		try:
			def _get_status():
				if daemon.status:
					print >>sys.stderr, "Daemon is running"
					raise SystemExit(0)
				else:
					raise DaemonStopped()

			actions = {
					"start" : daemon.start,
					"stop" : lambda: daemon.stop(stop_wait_time),
					"restart" : lambda: daemon.restart(stop_wait_time),
					"update" : daemon.update,
					"status" : _get_status,
					"foreground" : daemon.foreground,
					"kill" : daemon.kill
					}

			for signum in [signal.SIGUSR1, signal.SIGUSR2]:
				action_name = daemon.signal_alias.get(signum)
				if action_name:
					actions[action_name] = _make_killer(daemon, signum)

			if action not in actions:
				parser.error("Unknown action '%s'" % action)

			actions[action]()
			raise SystemExit(0)
		except SystemExit:
			raise
		except (DaemonStopped, DaemonRunning), e:
			if options.debug:
				traceback.print_exc()
			else:
				print >>sys.stderr, e
			raise SystemExit(1)
		except (IOError, OSError), e:
			if options.debug:
				traceback.print_exc()
			else:
				print >>sys.stderr, "%s: %s" % (e.__class__.__name__, e)
			print >>sys.stderr, "Are you running as root?"
			raise SystemExit(2)
		except Exception, e:
			if options.debug:
				traceback.print_exc()
			else:
				print >>sys.stderr, "%s: %s" % (e.__class__.__name__, e)
			raise SystemExit(3)
	return main
