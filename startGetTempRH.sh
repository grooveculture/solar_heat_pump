#!/bin/bash

# Check if gedit is running
# -x flag only match processes whose name (or command line if -f is
# specified) exactly match the pattern. 

currentDate=`date`
#if ps -x | grep 'node fetchTOventropVorRH.js' | grep -v grep > /dev/null 
#then
#    echo "already Running" $currentDate >> fetchTOventropRH.log
#else
#    node fetchTOventropVorRH.js
#fi


if ps -x | grep 'node fetchTOventropVorRH.js' | grep -v grep > /dev/null 
then
    echo "already Running" $currentDate >> fetchTOventropRH.log
    if  tail -10  fetchTOventropRH.log  |  grep already  > 5
	then
		echo "greater than 5 kill the process"
		pid=`ps -x | grep 'node fetchTOventropVorRH.js' | grep -v grep | awk '{ print $1 }'`
		kill $pid 
		rm fetchTOventropRH.log
		echo "killed process becaue it was hanging" $currentDate > fetchTOventropRH.log
	else
		echo "still ok"
	fi
else
    node fetchTOventropVorRH.js
fi