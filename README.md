first install requirements.txt

```shell
pip install -r requirements.txt
```
then activate the venv
```shell
.\.venv\Scripts\activate
```

to create the .exe run the build.bat file


if you need to recreate venv
````shell
python -m venv .venv
````

To create the package use
````
flet pack main.py --name "Gerador_Redmine" --icon "icon.ico"
````
