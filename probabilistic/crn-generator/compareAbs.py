#!/usr/bin/env python3
#
# Compare abstractions in the CSV-like format of SeQuaiA
# (https://sequaia.model.in.tum.de/)
#

import argparse
import sys

from ast import literal_eval


def read_abstraction(filename):
	"""Read the abstractions from file"""

	relation = {}

	with open(filename, 'r') as ifile:
		ifile.readline()  # Discard the line with the levels
		ifile.readline()  # Discard the line with the initial state
		ifile.readline()  # Discard the CSV header

		for line in ifile:
			if line.isspace():
				continue

			origin, dest, p, ex_t = map(literal_eval, line.split(';')[:4])

			odict = relation.setdefault(origin, {})
			odict[dest] = p, ex_t

	return relation


def compare(abs1, abs2, epsilon=0.1, time_epsilon=float('inf')):
	"""Compare two abstractions"""

	not_at_all = []
	missing_children = []
	probability_error = []
	time_error = []

	absn = abs1, abs2

	# States with successors that are in #2 but not in #1
	if len(abs2) > len(abs1):
		for origin in abs2.keys():
			if origin not in abs1:
				not_at_all.append((1, origin))

	# Review all states in #1
	for origin, succs1 in abs1.items():
		succs2 = abs2.get(origin)

		# States with successors in #1 that are not in #2
		if succs2 is None:
			not_at_all.append((2, origin))

		else:
			# Successors from origin that are not in #1 but they are in #2
			if len(succs2) > len(succs1):
				for dest in succs2.keys():
					if dest not in succs1:
						missing_children.append((1, origin, dest))

			for dest, (p1, ex_t1) in succs1.items():
				p2, ex_t2 = succs2.get(dest, (None, None))

				if p2 is None:
					missing_children.append((2, origin, dest))

				else:
					if abs(p1 - p2) >= epsilon:
						probability_error.append((origin, dest, p2 - p1))

					if abs(ex_t1 - ex_t2) >= time_epsilon:
						time_error.append((origin, dest, ex_t2 - ex_t1))

	# Print the results by categories
	width = 3 * len(next(iter(abs1.keys()), ())) + 2

	if not_at_all:
		print('\x1b[1mStates without any successor\x1b[0m')
		for side, origin in not_at_all:
			p = sum((p for p, _ in absn[2 - side][origin].values()))
			dests = ' '.join((str(dest) for dest in absn[2 - side][origin].keys()))
			print(f'\x1b[36m({side})\x1b[0m {str(origin):{width}} p = {p} dest = {dests}')

	if missing_children:
		print('\n\x1b[1mStates with missing children\x1b[0m')
		for side, origin, dest in missing_children:
			p, _ = absn[2 - side][origin][dest]
			print(f'\x1b[36m({side})\x1b[0m {str(origin):{width}} -> {str(dest):{width}} p = {p}')

	if probability_error:
		print('\n\x1b[1mProbability errors\x1b[0m')
		for origin, dest, dp in probability_error:
			print(f'{str(origin):{width}} -> {str(dest):{width}} error = {round(dp, 3)}')

	if time_error:
		print('\n\x1b[1mTime errors\x1b[0m')
		for origin, dest, dt in time_error:
			print(f'{str(origin):{width}} -> {str(dest):{width}} error = {round(dt, 3)}')


def convert_dot(abst, ofile):
	"""Convert abstraction to DOT format"""

	ofile.write('digraph {\n')

	for origin, succs in abst.items():
		for dest, (p, ex_t) in succs.items():
			ofile.write(f'\t"{origin}" -> "{dest}" [label="p={round(p, 4)} t={round(ex_t, 4)}"];\n')

	ofile.write('}\n')


if __name__ == '__main__':

	parser = argparse.ArgumentParser(description='Compare generated abstractions')
	parser.add_argument('abstr1', help='Abstraction 1')
	parser.add_argument('abstr2', help='Abstraction 2', nargs='?')
	parser.add_argument('-e', '--epsilon', help='Epsilon for probability errors', type=float, default=0.1)
	parser.add_argument('-t', '--time', help='Epsilon for time errors', type=float, default=0.1)
	args = parser.parse_args()

	abs1 = read_abstraction(args.abstr1)
	abs2 = read_abstraction(args.abstr2) if args.abstr2 else None

	if abs2 is None:
		if not sys.stdout.isatty():
			convert_dot(abs1, sys.stdout)
		else:
			with open('abstraction.dot', 'w') as ofile:
				convert_dot(abs1, ofile)
	else:
		compare(abs1, abs2, epsilon=args.epsilon, time_epsilon=args.time)
