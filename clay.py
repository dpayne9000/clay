#!/usr/bin/env python3
from clay import cli
import logging
import sys

logging.basicConfig(level=logging.DEBUG, filename='workflow.log', filemode='w', format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    sys.exit(cli.cli())

if __name__ == "__main__":
    main()