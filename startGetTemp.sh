#!/bin/bash

# Check if gedit is running
# -x flag only match processes whose name (or command line if -f is
# specified) exactly match the pattern. 

currentDate=`date`
# if ps -x | grep 'node fetchTOventrop.js' | grep -v grep > /dev/null 
# then
#     echo "already Running" $currentDate >> fetchTOventrop.log
# else
#     node fetchTOventrop.js
# fi

if ps -x | grep 'node fetchTOventrop.js' | grep -v grep > /dev/null 
then
    echo "already Running" $currentDate >> fetchTOventrop.log
    if  tail -10  fetchTOventrop.log  |  grep already  > 5
	then
		echo "greater than 5 kill the process"
		pid=`ps -x | grep 'node fetchTOventrop.js' | grep -v grep | awk '{ print $1 }'`
		kill $pid 
		rm fetchTOventrop.log
		echo "killed process becaue it was hanging" $currentDate > fetchTOventrop.log
	else
		echo "still ok"
	fi
else
    node fetchTOventrop.js
fi