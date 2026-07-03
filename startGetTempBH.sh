#!/bin/bash

# Check if gedit is running
# -x flag only match processes whose name (or command line if -f is
# specified) exactly match the pattern. 

currentDate=`date`
#if ps -x | grep 'node fetchTOventropVorBH.js' | grep -v grep > /dev/null 
#then
#    echo "already Running" $currentDate >> fetchTOventropBH.log
#else
#    node fetchTOventropVorBH.js
#fi


if ps -x | grep 'node fetchTOventropVorBH.js' | grep -v grep > /dev/null 
then
    echo "already Running" $currentDate >> fetchTOventropOutside.log
    if  tail -10  fetchTOventropOutside.log  |  grep already  > 5
	then
		echo "greater than 5 kill the process"
		pid=`ps -x | grep 'node fetchTOventropVorBH.js' | grep -v grep | awk '{ print $1 }'`
		kill $pid 
		rm fetchTOventropBH.log
		echo "killed process becaue it was hanging" $currentDate > fetchTOventropBH.log
	else
		echo "still ok"
	fi
else
    node fetchTOventropVorBH.js
fi