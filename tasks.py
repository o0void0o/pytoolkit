# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import datetime
import os.path
import sys
from datetime import date
from urllib.request import HTTPBasicAuthHandler

DB = "C:/work/tasks.adoc"

if not os.path.isfile(DB):
    with open(DB, 'w'): pass

def line_prepender(filename, line):
    with open(filename, 'r+') as f:
        content = f.read()
        f.seek(0, 0)
        f.write(line.rstrip('\r\n') + '\n' + content)

if len(sys.argv)>1:
     print (date.today())
     print ("-----------------------")
     print('')

     with open(DB, 'r+') as f:
        myline = f.readline()
        while myline:
            if myline[27] =='0':
               print(myline[29:])     
            myline = f.readline()

        f.close()   
else:
    date = str(datetime.datetime.now())
    line = date+ " 0 " + input("Type the task: ")
    with open(DB, 'a') as f:
        f.writelines(line)

