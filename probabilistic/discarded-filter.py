#!/usr/bin/env python3
#
# Calculate conditional probabilities without discarded executions
#

import fractions
import re
import sys


def parse_line(line):
	"""Parse the output of state probabilities in umaudemc"""

	# If line does not start with space, we assume it is a comment
	if not line.startswith(' '):
		return None, line[:-1]

	sep = line.index(' ', 1)
	p = line[:sep].strip()
	term = line[sep:].strip()

	if '/' in p:
		num, den = map(int, p.split('/'))
		p = num / den
	else:
		p = float(p)

	return p, term


def print_frac(value):
	"""Print a floating-point number as a fraction"""

	num, den = fractions.Fraction(value).limit_denominator().as_integer_ratio()

	return f'{num}/{den}' if num > 0 and den != 1 else num


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser(description='Conditional probabilities without discarded executions')
	parser.add_argument('--fraction', '-f', help='Show aproximate fractions for the probabilities', action='store_true')
	parser.add_argument('--regex', '-r', help='Regular expression describing the discarded terms', default='discarded')

	args = parser.parse_args()

	regex = re.compile(args.regex)
	display = print_frac if args.fraction else lambda x: x
	dp, results = 0.0, []

	for p, term in map(parse_line, sys.stdin):
		if p is not None and regex.fullmatch(term):
			dp += p
		else:
			results.append((p, term))

	if dp == 1.0:
		print('No valid result.')
	else:
		for p, t in results:
			print(t if p is None else f' {display(p / (1.0 - dp)):<20} {t}')
