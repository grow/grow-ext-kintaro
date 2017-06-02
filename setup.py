from setuptools import setup


setup(
    name='grow',
    zip_safe=False,
    license='MIT',
    author='Grow SDK Authors',
    author_email='hello@grow.io',
    include_package_data=False,
    py_modules=[
        'kintaro',
    ],
    install_requires=[
        'google-api-python-client',
    ],
)
