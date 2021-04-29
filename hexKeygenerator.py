import numpy.random
size=int(input("Enter key bit lenth:"))
if size%8 !=0:
	print("The key bit length may not produce a remainder when divided by 8. They again... ")
print(numpy.random.bytes(size/8).hex())