from setuptools import find_packages, setup

setup(
    name='csa',
    version='0.2.1',
    description='Code Structure Analyzer',
    packages=find_packages(include=['csa*']),
    python_requires='>=3.10',
)
