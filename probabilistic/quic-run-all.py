#
# Run several cases of the QUIC example
#

import itertools
import json
import os
import subprocess
import sys
import time

# Packet loss probabilities
ps = (0.005, 0.01, 0.02, 0.025, 0.05, 0.1, 0.15, 0.2)


class Runner:
	def __init__(self):
		self.env = os.environ.copy()
		# self.env['PYTHONPATH'] = '<for local installations of umaudemc>'

	def run_http3(self, num_streams, p, variant='first', seed=None):
		"""Run a simulation for HTTP3"""

		delta = self.radius(p)

		cmd_line = [
			sys.executable, '-m', 'umaudemc', 'scheck',
			'quic',  # Input file
			'-m', 'HTTP3-CHECK',  # Module
			f'initial({num_streams}, true)',  # Initial term
			'--assign', f'uaction(channel-loss.p={p})',  # Assignment method
			f'quic-{variant}.quatex',  # QuaTEx file
			'step !',  # Strategy
			'-d', str(delta),  # Radius of the confidence interval
			'--format', 'json',  # Output in JSON
		]

		if seed is not None:
			cmd_line += ['--seed', str(args.seed)]

		start_time = time.process_time_ns()
		raw = subprocess.run(cmd_line, stdout=subprocess.PIPE, env=self.env)
		end_time = time.process_time_ns()

		result = json.loads(raw.stdout) | {
			'time': end_time - start_time,
			'delta': delta,
			'query': variant,
			'p': p,
			'num_streams': num_streams,
			'http': 3,
		}

		return result

	def run_http2(self, num_streams, p, variant='first', seed=None):
		"""Run a simulation for HTTP2"""

		delta = self.radius(p)

		cmd_line = [
			sys.executable, '-m', 'umaudemc', 'scheck',
			'quic',  # Input file
			'-m', 'HTTP2-CHECK',  # Module
			f'initial({num_streams}, true)',  # Initial term
			'--assign', f'uaction(channel-loss.p={p})',  # Assignment method
			f'quic-{variant}.quatex',  # QuaTEx file
			'step !',  # Strategy
			'-d', str(delta),  # Radius of the confidence interval
			'--format', 'json',  # Output in JSON
		]

		if seed is not None:
			cmd_line += ['--seed', str(args.seed)]

		start_time = time.process_time_ns()
		raw = subprocess.run(cmd_line, stdout=subprocess.PIPE, env=self.env)
		end_time = time.process_time_ns()

		result = json.loads(raw.stdout) | {
			'time': end_time - start_time,
			'delta': delta,
			'query': variant,
			'p': p,
			'num_streams': num_streams,
			'http': 2,
		}

		return result

	def radius(self, p):
		if p < 0.05:
			return 0.1
		elif p < 0.1:
			return 0.3
		else:
			return 0.5


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser(description='Execute scheck on the quic.maude example and capture the results')

	parser.add_argument('version', help='HTTP version', choices=['2', '3'])
	parser.add_argument('--streams', help='Number of streams', type=int, default=5)
	parser.add_argument('--seed', help='Random seed', type=int)

	args = parser.parse_args()

	rn = Runner()
	cmd = rn.run_http2 if args.version == '2' else rn.run_http3

	for p, variant in itertools.product(ps, ('first', 'last')):
		json.dump(cmd(args.streams, p, variant, seed=args.seed), sys.stdout)
		print()
