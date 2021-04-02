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
from tqdm import tqdm

if len(sys.argv)<4:
   print ('usage:')
   print ('port.py <ip_address> <LowestPort> <HighestPort>')
   print ('For example:')
   print ('port-scan.py 127.0.0.1 80 1999')
   print ('will scan for open ports on 127.0.0.1 in the range 80 to and including 1999.')
   exit()

server_ip=sys.argv[1]
port_low=int(sys.argv[2])
port_high=int(sys.argv[3])

open_ports=[]
for i in tqdm(range(port_low,port_high)):
   s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
   socket.setdefaulttimeout(1)
   result=s.connect_ex((server_ip,i))       
   if result == 0:
      open_ports.append(i)
      s.close()
  
if len(open_ports):
   print("Open ports")
   for i in open_ports:
      print(str(i))
else:
   print("No open ports found in the provided range:"+str(port_low)+" to "+str(port_high))
