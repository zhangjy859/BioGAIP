import hashlib
import argparse
import os

def hash_password(pwd, salt):
    return hashlib.sha256((pwd + salt).encode('utf-8')).hexdigest()

def main():
    parser = argparse.ArgumentParser(description="Generate user:password file for BioGAIP")
    parser.add_argument("-u", "--username", required=True, help="Username")
    parser.add_argument("-p", "--password", required=True, help="Password (plain text)")
    parser.add_argument("-s", "--salt", help="Salt for password encryption (optional, must match PASSWORD_SALT env var)", default="")
    parser.add_argument("-f", "--file", help="Output file (default: users.txt)", default="users.txt")
    
    args = parser.parse_args()
    
    # Hash the password if salt is provided, otherwise keep plain text
    final_password = hash_password(args.password, args.salt) if args.salt else args.password
    
    record = f"{args.username}:{final_password}\n"
    
    with open(args.file, "a") as f:
        f.write(record)
        
    print(f"User '{args.username}' successfully added to {args.file}")
    if args.salt:
        print("Note: Password was encrypted using the provided salt.")
        print(f"Please ensure 'export PASSWORD_SALT=\"{args.salt}\"' is set before running the app.")
    else:
        print("Note: Password was saved in plain text.")
        print("For better security, consider using the -s/--salt argument.")

if __name__ == "__main__":
    main()