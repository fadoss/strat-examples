#!/bin/bash
#
# Program for testing the examples, checking that their output coincide
# with the expected one.
#
# Tests are text file whose first line is the path of the main Maude
# file to be load, followed by an empty line and then some commands to be
# executed by Maude. If no file is given as argument all files with .test
# extension will be checked.
#
# Expected results are read from files with .out extension. When no such
# file exists it will be generated with the program output. Otherwise, the
# program output is compared on the fly and not saved.

# Transfer lines from the test file to Maude
transferLines () {
	read -r -u $1 line
	while [ $? -eq 0 ];
	do
		if [ "$line" != "" ]
		then
			echo -E "$line" >&$2
		fi
		read -r -u $1 line
	done
}

# Executes some common commands and then the test file
feedMaude () {
	echo "set show timing off ." >&$2
	echo "load $3" >&$2
	transferLines $1 $2
	echo "quit ." >&$2

	wait $COPROC_PID
}

# Encode the combined status of Maude and Diff
encodeStatus () {
	if [ $1 -ne 0 ]
	then
		return 3
	else
		return $2
	fi
}

# Apply a test
applyTest () {

	testdir="$(pwd)"
	outfile="$(basename $1 | cut -d. -f1).out"

	exec 3< "$1"
	read -u 3 mfile

	sourcedir="../$(dirname $mfile)"

	if [ -f "$outfile" ]
	then
		echo -e "\x1b[1mTesting file\x1b[0m $mfile"

		coproc { cd "$sourcedir" ; "$SMAUDE" -no-advise -no-banner | diff --strip-trailing-cr -u "$testdir/$outfile" - ; encodeStatus ${PIPESTATUS[*]} ; } >&2
		feedMaude 3 ${COPROC[1]} "$(basename $mfile)"

		returnValue=$?

		echo -en "\x1b[1;31m"
		case $returnValue in
			1) 	echo "Output differ" ;;
			2) 	echo "Diff error" ;;
			3) 	echo "Maude error" ;;
		esac
		echo -en "\x1b[0m"
	else
		echo -e "\x1b[1mExecuting\x1b[0m $mfile \x1b[1mfor the first time\x1b[0m"

		coproc { cd "$sourcedir" ; "$SMAUDE" -no-advise -no-banner ; } > "$testdir/$outfile"
		feedMaude 3 ${COPROC[1]} "$(basename $mfile)"

		if [ $? -ne 0 ]
		then
			echo "Maude error"
			rm "$outfile"
		fi
	fi
}

#
# Script code
#

if [ -z "$SMAUDE" ]; then
    echo "Please, set SMAUDE enviroment variable to the path of the Maude binary."
    exit 1
fi

if [ "$#" -gt 0 ]; then
	for TEST in "${@:1}"
	do
		applyTest "$TEST"
	done
else
	for TEST in *.test
	do
		applyTest "$TEST"
	done
fi
