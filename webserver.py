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

import http.server
import socketserver
import socket   
import sys 

web_svr_port = 80

if len(sys.argv)>1:
    web_svr_port=int(sys.argv[1])

rqHandler = http.server.SimpleHTTPRequestHandler
rqHandler.extensions_map.update({
    '.webapp': 'application/x-web-app-manifest+json',
});

server = socketserver.TCPServer(("", web_svr_port), rqHandler)

print("Web server started on: " + socket.gethostname())   
print ("Serving at port: ", web_svr_port)

server.serve_forever()
