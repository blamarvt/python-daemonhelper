from base import make_main, Daemon
import os, subprocess, signal, time

def create_wrapper_class(script_path, daemon_name=None, script_args=(), autorestart=0):
	if autorestart:
		autorestart = int(autorestart)

	class WrapperDaemon(Daemon):
		name = daemon_name or os.path.basename(script_path).split(".")[0]
		
		def handle_run(self):
			args = [script_path]
			args.extend(script_args or ())
			
			self._go = True
			while self._go:
				self._go = bool(autorestart)

				self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

				while True:
					try:
						line = self.process.stdout.readline()
					except IOError:
						break

					if not line:
						break
					
					line = line.rstrip()
					if not line:
						continue

					self.logger.info(line)

				retval = self.process.wait()
				
				if self._go:
					self.logger.critical("process died unexpectedly with code %d, will restart in %ds" % (retval, autorestart))
					time.sleep(autorestart)

				elif retval != 0:
					raise SystemExit(retval)

		def handle_stop(self, *_):
			self._go = False
			try:
				os.kill(self.process.pid, signal.SIGTERM)
			except OSError:
				pass

	return WrapperDaemon

def make_wrapper_main(script_path, daemon_name=None, script_args=(), autorestart=0):
	daemon_obj = create_wrapper_class(script_path, daemon_name, script_args, autorestart)
	return make_main(daemon_obj)

def exec_wrapper(script_path, daemon_name=None, script_args=(), autorestart=0):
	make_wrapper_main(script_path, daemon_name, script_args, autorestart)()

if __name__ == "__main__":
	exec_wrapper("/bin/sleep", "sleeper", ("2",), 3)
