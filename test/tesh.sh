#!/bin/bash
# Purpose: automate the testing currently given in manual.txt

# This should be run in the vagrant environment
# It will definitely require installation of additional python packages
# Perhaps change the chef setup to install them by default?

# Start running the server in the background
paster serve --reload ../r2/development.ini &

# Save the paster server's pid
paster_PID=$!

#Here we need to install whatever additional Python packages are needed
#At a minimum I plan to use Mechanize
#In the long-run, it will likely be easier to fiddle with the vagrant provisioning to install all of this by default

#Run tests using mechanize
python test.py

#At the end, stop running the server
kill $paster_PID


