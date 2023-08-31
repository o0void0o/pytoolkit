import random

def generate_card_number(bin: str, length: int = 19):
    """Generates a random card number with a given BIN and length."""
    # Start with the bin
    number = bin
    # Generate the remaining digits randomly, except for the last digit
    while len(number) < length - 1:
        digit = random.choice('0123456789')
        number += digit

    # Compute the last digit with the Luhn algorithm
    number += luhn_checksum(number)
    return number

def luhn_checksum(card_number: str) -> str:
    """Generates a Luhn checksum for the card number."""
    def digits_of(n):
        return [int(d) for d in str(n)]
    
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = 0
    checksum += sum(odd_digits)
    checksum += sum(sum(digits_of(d*2)) for d in even_digits)
    return str((10 - checksum % 10) % 10)

# Use the function
bin = '4929100'
custom_bin=input("enter a 6 digit bin.. elsse leave empty for 4929100")
if is custom_bin
    bin=custom_bin
for _ in range(10):
    print(generate_card_number(bin))