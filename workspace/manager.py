import os
import sys

class Manager:
    def __init__(self):
        self.workspace = os.getcwd()
        print(f'Workspace: {self.workspace}')