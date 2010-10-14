from daemonhelper import Daemon, make_main
import time

class MyDaemon(Daemon):
	"""
	Example daemon just spams syslog with 'ping' and a value. The value is configured
	by /etc/mydaemon.conf (always /etc/${name}.conf).

	$ cat /etc/mydaemon.conf
	[mydaemon]
	value: lolcats
	
	The config file may be changed, which the daemon will detect on SIGHUP:
	$ # Config reload/polling is broken right now, will fix soon
	$ sudo python example.py start
	$ tail /var/log/messages
	... mydaemon INFO: ping! defaultvalue
	$ vi /etc/mydaemon.conf
	$ sudo python example.py update
	$ tail /var/log/message
	... mydaemon INFO: ping! somenewvalue

	Run the daemon in the foreground to get debug logging and respond to ctrl-c (SIGINT):
	$ sudo python example.py foreground
	"""

	name = "mydaemon"
	description = "I'm so cool"

	def handle_prerun(self):
		self.logger.info("handle_prerun always runs as root")
		self._shutdown = False

	def handle_run(self):
		self.logger.info("handle_run is run as a configured user (default is root)")
		while not self._shutdown:
			some_config_value = self.config("mydaemon", "somevalue", "defaultvalue")
			self.logger.info("ping! %r" % some_config_value)
			time.sleep(2)
		self.logger.warning("oh no I'm totally dead!")

	def handle_stop(self):
		self.logger.info("trying to shutdown")
		self._shutdown = True

# Create a main function, with help and fancy option parsing
main = make_main(MyDaemon)

if __name__ == "__main__":
	main()
