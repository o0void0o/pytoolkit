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

DB = "notes.adoc"

if not os.path.isfile(DB):
    with open(DB, 'w'): pass

def line_prepender(filename, line):
    with open(filename, 'r+') as f:
        content = f.read()
        f.seek(0, 0)
        f.write(line.rstrip('\r\n') + '\n' + content)

date = str(datetime.datetime.now())
line = date+ " " + input("Type the note: ")
line_prepender(DB, line)

# very simple note dumping scrippy. The latest goes to the top. The addded note is prepended
# with the date. The notes live in the DB consants file.
