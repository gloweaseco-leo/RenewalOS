"""Local secure-mode account provisioning; credentials never passed as CLI arguments."""
import argparse
from getpass import getpass
from .access import initialize_access, create_local_user


def main():
    parser=argparse.ArgumentParser(description='Create RenewalOS local user')
    parser.add_argument('username')
    parser.add_argument('--store',required=True)
    parser.add_argument('--role',required=True,choices=['staff','manager','auditor'])
    args=parser.parse_args()
    password=getpass('New password (>=12 characters): ')
    if password!=getpass('Repeat password: '):
        parser.error('Password confirmation mismatch')
    initialize_access()
    create_local_user(args.username,password,{args.store:args.role})
    print('Local account created. Password was not stored in plaintext.')

if __name__=='__main__':main()
