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
    
import socket
import sys

if len(sys.argv)<3:
   print ('usage:')
   print ('port.py <ip_address> <port>')
   print ('for example:')
   print ('port.py 127.0.0.1 80')
   exit()

socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = socket.connect_ex((sys.argv[1],int(sys.argv[2])))

if result == 0:
   print ("Port "+sys.argv[2]+" is open!")
else:
   print ("Port "+sys.argv[2]+" is not open.")

socket.close()