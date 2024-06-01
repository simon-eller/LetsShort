import telebot
from telebot import types
from requests import get
import firebase_admin
from firebase_admin import credentials
from firebase_admin import db
from time import sleep
import os
from flask import Flask, request
from csv import reader
import json
import lsbtranslations
import urllib3 as urllib
from bs4 import BeautifulSoup
import certifi

# Shortener class for different providers
class Shortener(object):
    def __init__(self, url):
        self.url = url

    def get_url(self):
        return self.url

# Create shortener objects
TINYURL = Shortener("https://tinyurl.com/api-create.php?url=")
ISGD = Shortener("https://is.gd/create.php?format=json&url=")
VGD = Shortener("https://v.gd/create.php?format=json&url=")
CUTTLY = Shortener("https://cutt.ly/api/api.php?key=" + os.environ.get('CUTTLY_API_TOKEN'))

# Fetch the service account key JSON file contents
cred_raw = os.environ.get('FIREBASE_KEY')
cred = credentials.Certificate(cred_raw)

# Initialize the app with a service account, granting admin privileges
firebase_admin.initialize_app(cred, {
    'databaseURL': os.environ.get('FIREBASE_DB_URL')
})

# Initialize database path to root
ref = db.reference('/')

# Read private token from env-file
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

# Read owner id from env-file
OWNER_ID = os.environ.get('TELEGRAM_BOT_OWNER')
knownUsers = []
server = Flask(__name__)

ref2 = db.reference('user')
snapshot = ref2.order_by_key().get()

# get all users from database and save it in list
for key in snapshot.items():
    x = key
    knownUsers.append(x[0])

userStep = {}  # so they won't reset every time the bot restarts

translations = lsbtranslations.get_translations()

hideBoard = types.ReplyKeyboardRemove(selective=False)  # if sent as reply_markup, will hide the keyboard

# error handling if user isn't known yet
# (obsolete once known users are saved to file, because all users
#   had to use the /start command and are therefore known to the bot)
def get_user_step(uid):
    if uid in userStep:
        return userStep[uid]
    else:
        knownUsers.append(uid)
        userStep[uid] = 0
        print("New user detected, who hasn't used \"/start\" yet")
        return 0

# only used for console output now
def listener(messages):

    # When new messages arrive TeleBot will call this function.
    for m in messages:
        if m.content_type == 'text':
            # print the sent message to the console
            print(str(m.chat.first_name) + str(m.chat.last_name) + " [" + str(m.chat.id) + "]: " + m.text)

bot = telebot.TeleBot(TOKEN)
bot.set_update_listener(listener)  # register listener

# handle the "/start" command
@bot.message_handler(commands=['start'])
def command_start(m):
    cid = m.chat.id
    if cid not in knownUsers:  # if user hasn't used the "/start" command yet:
        knownUsers.append(cid)  # save user id, so you could brodcast messages to all users of this bot later
        userStep[cid] = 0  # save user id and his current "command level", so he can use the "/getImage" command
        save(m.chat) # saves user in db
        command_language(m)
        sleep(5)
        try:
            lang = get_lang(cid)
            bot.send_message(cid, translations[lang]['welcome'])
            command_help(m)  # show the new user the help page
        except:
            sleep(10)
            try:
                lang = get_lang(cid)
                bot.send_message(cid, translations[lang]['welcome'])
                command_help(m)  # show the new user the help page
            except:
                bot.send_message(cid, translations['en']['welcome'])
                command_help(m)

    else:
        lang = get_lang(m)
        bot.send_message(cid, translations[lang]['know'])

# help page
@bot.message_handler(commands=['help'])
def command_help(m):
    cid = m.chat.id
    lang = get_lang(cid)
    help_text = translations[lang]['help_text']
    for key in translations[lang]['commands']:  # generate help text out of the commands dictionary defined at the top
        help_text += "/" + key + ": "
        help_text += translations[lang]['commands'][key] + "\n"
    bot.send_message(cid, help_text)  # send the generated help page

# about information
@bot.message_handler(commands=['about'])
def command_about(m):
    cid = m.chat.id
    lang = get_lang(cid)
    bot.send_message(cid, translations[lang]['about'])

# change the url shortener
@bot.message_handler(commands=['change'])
def change_shortener(m):
    cid = m.chat.id
    lang = get_lang(cid)
    shortenerSelect = types.ReplyKeyboardMarkup(one_time_keyboard=True)  # create the language selection keyboard
    shortenerSelect.add('Tinyurl', 'Cuttly', 'YOURLS', 'IS.GD', 'V.GD')
    bot.send_message(cid, translations[lang]['change-shortener'], reply_markup=shortenerSelect)  # show the keyboard
    userStep[cid] = 5  # set the user to the next step (expecting a reply in the listener now)

# if the user has issued the "/change" command, process the answer
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 5)
def command_change_shortener2(m):
    cid = m.chat.id
    text = m.text
    lang = get_lang(cid)
    if text == "Tinyurl":
        change_shortener(cid, "tiny")
        bot.send_message(cid, translations[lang]['tiny'], reply_markup=hideBoard)
        userStep[cid] = 0

    elif text == "Cuttly":
        change_shortener(cid, "cuttly")
        bot.send_message(cid, translations[lang]['cuttly'], reply_markup=hideBoard)
        userStep[cid] = 0

    elif text == "YOURLS":
        yourls_config = get_yourls_link(cid)

        # if no yourls configuration was already added to database
        if yourls_config == "0" or yourls_config == 0 or yourls_config == "reset":      #TODO: check if this works
            bot.send_message(cid, translations[lang]['yourls1'])
            userStep[cid] = 1  # set the user to the next step (expecting a reply in the listener now)

        # if a yourls api was already configured before
        else:
            yourls_link = get_yourls_link(str(cid))
            change_shortener(cid, yourls_link)
            bot.send_message(cid, translations[lang]['yourls3'], reply_markup=hideBoard)

            # send stats of yourls configuration
            yourls_stats_url = yourls_link + "&action=stats&format=json"
            try:
                response = get(yourls_stats_url).json()
                if int(response['statusCode']) == 200:
                    message = translations[lang]['yourls-stats']['1'] + str(response['stats']['total_links']) + translations[lang]['yourls-stats']['2'] + str(response['stats']['total_clicks'])
                    bot.send_message(cid, message, reply_markup=hideBoard)
                else:
                    bot.send_message(cid, translations[lang]['yourls-error'], reply_markup=hideBoard)
            except:
                bot.send_message(cid, translations[lang]['yourls-error'], reply_markup=hideBoard)
            userStep[cid] = 0

    elif text == "IS.GD":
        change_shortener(cid, "isgd")
        bot.send_message(cid, translations[lang]['isgd'], reply_markup=hideBoard)
        userStep[cid] = 0

    elif text == "V.GD":
        change_shortener(cid, "vgd")
        bot.send_message(cid, translations[lang]['vgd'], reply_markup=hideBoard)
        userStep[cid] = 0

# if the user has issued the "/yourls" command the second time
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 1)
def command_yourls2(m):
    cid = m.chat.id
    text = m.text
    change_shortener(cid, text)
    lang = get_lang(cid)
    bot.send_message(cid, translations[lang]['yourls2'], reply_markup=hideBoard)
    userStep[cid] = 0

# resets the default settings
@bot.message_handler(commands=['reset'])
def command_reset(m):
    cid = m.chat.id
    reset(cid)
    lang = get_lang(cid)
    bot.send_message(cid, translations[lang]['reset'], reply_markup=hideBoard)

# that the user can see all his shortened links
@bot.message_handler(commands=['mylinks'])
def command_mylinks(m):
    cid = str(m.chat.id)
    bot.send_message(cid, get_urls(cid))

# show stats of a link
@bot.message_handler(commands=['stats'])
def command_stats(m):
    cid = str(m.chat.id)
    path = "user/" + cid
    # Set reference path
    ref = db.reference(path)
    # Get data from database
    prov = ref.get("provider")
    tup = prov[0]
    prov = tup["provider"]

    lang = get_lang(m.chat.id)

    if "cutt.ly" in m.text:
        url = CUTTLY.get_url() + "&stats=" + m.text[8:len(m.text)]
        response = get(url).json()['stats']
        status = response['status']

        if status == 1:
            message = translations[lang]['title'] + response['title'] + "\n" + translations[lang]['date'] + response['date'] + "\n" + translations[lang]['full-link'] + response['fullLink'] + "\n" + translations[lang]['clicks'] + str(response['clicks'])
        else:
            message = translations[lang]['error']

    elif "is.gd" in m.text:
        if m.text[7]=="h" and m.text[11]=="s":
            url = "https://is.gd/stats.php?allref=1&url=" + m.text[21:len(m.text)]
            stats = extract_stats(url)
            if stats[0] == 0:
                message = translations[lang]['ssl-error']                                                   #if there is an ssl certificate error

            elif "Sorry" in stats[0]:
                message = translations[lang]['isgd-missing']                                                #if the link is not in the database

            else:
                stats[0] = stats[0].replace("This shortened URL (", translations[lang]['short-link'])       #replace original english text with text from other languages
                stats[0] = stats[0].replace(") redirects to:", "\n" + translations[lang]['full-link'])
                message = stats[0] + "\n" + translations[lang]['clicks'] + str(stats[1])

        elif m.text[7] == "i":      #if the users sends the link without https://
            url = "https://is.gd/stats.php?allref=1&url=" + m.text[13:len(m.text)]
            stats = extract_stats(url)
            if stats[0] == 0:
                message = translations[lang]['ssl-error']
            else:
                message = stats[0] + "\n" + translations[lang]['clicks'] + str(stats[1])
        else:
            message =  translations[lang]['isgd-stats-error']

    elif "v.gd" in m.text:
        if m.text[7] == "h" and m.text[11] == "s":  #if the user sends the link with https://
            url = "https://v.gd/stats.php?allref=1&url=" + m.text[20:len(m.text)]
            stats = extract_stats(url)
            if stats[0] == 0:
                message = translations[lang]['ssl-error']

            elif "Sorry" in stats[0]:
                message = translations[lang]['isgd-missing']

            else:
                stats[0] = stats[0].replace("This shortened URL (", translations[lang]['short-link'])
                stats[0] = stats[0].replace(") redirects to:", "\n" + translations[lang]['full-link'])
                message = stats[0] + "\n" + translations[lang]['clicks'] + str(stats[1])

        elif m.text[7] == "v":  #if the user sends the link without https://
            url = "https://v.gd/stats.php?allref=1&url=" + m.text[12:len(m.text)]
            stats = extract_stats(url)
            if stats[0] == 0:
                message = translations[lang]['ssl-error']
            else:
                message = stats[0] + "\n" + translations[lang]['clicks'] + str(stats[1])
        else:
            message = translations[lang]['isgd-stats-error']

    elif "tinyurl" in m.text:
        message = "Stats are unavailable for tinyurl at the moment."

    else:
        if m.text[7] == "h": #if the link is with https
            url = get_yourls_link(cid) + "&action=url-stats&format=json&shorturl=" + m.text[7:len(m.text)]
            try:
                response = get(url).json()
                if int(response['statusCode']) == 200:
                    message = translations[lang]['title'] + response['link']['title'] + "\n" + translations[lang]['date'] + response['link']['timestamp'] + "\n" + translations[lang]['full-link'] + response['link']['url'] + "\n" + translations[lang]['clicks'] + response['link']['clicks']

                elif int(response['statusCode']) == 404:
                    message = translations[lang]['yourls-error-404']
            except:
                message = translations[lang]['yourls-error']
        else:
            url = get_yourls_link(cid) + "&action=url-stats&format=json&shorturl=https://" + m.text[7:len(m.text)]
            try:
                response = get(url).json()
                if int(response['statusCode']) == 200:
                    message = translations[lang]['title'] + response['link']['title'] + "\n" + translations[lang][
                        'date'] + response['link']['timestamp'] + "\n" + translations[lang]['full-link'] + \
                              response['link']['url'] + "\n" + translations[lang]['clicks'] + response['link']['clicks']

                elif int(response['statusCode']) == 404:
                    message = translations[lang]['yourls-error-404']
            except:
                message = translations[lang]['yourls-error']

    bot.send_message(cid, message)

# user select language
@bot.message_handler(commands=['language'])
def command_language(m):
    languageSelect = types.ReplyKeyboardMarkup(one_time_keyboard=True)  # create the language selection keyboard
    languageSelect.add('English', 'Deutsch')
    cid = m.chat.id
    bot.send_message(cid, "Language/Sprache", reply_markup=languageSelect)  # show the keyboard
    userStep[cid] = 2  # set the user to the next step (expecting a reply in the listener now)


# if the user has issued the "/language" command, process the answer
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 2)
def command_language2(m):
    cid = m.chat.id
    text = m.text

    if text == 'English':
        try:
            change_language(cid,'en')
            bot.send_message(cid, "The language was changed to English.", reply_markup=hideBoard)
        except:
            bot.send_message(cid, "An error occured, please contact the admin.", reply_markup=hideBoard)
        userStep[cid] = 0  # reset the users step back to 0

    elif text == 'Deutsch':
        try:
            change_language(cid,'de')
            bot.send_message(cid, "Die Sprache wurde zu Deutsch geändert.", reply_markup=hideBoard)
        except:
            bot.send_message(cid, "Ein Fehler ist aufgetreten, kontaktieren Sie den Admin.", reply_markup=hideBoard)
        userStep[cid] = 0
    else:
        bot.send_message(cid, "Please, use the predefined keyboard!")
        bot.send_message(cid, "Please try again")

# privacy menu
@bot.message_handler(commands=['privacy'])
def command_privacy(m):
    cid = m.chat.id
    lang = get_lang(cid)
    privacySelect = types.ReplyKeyboardMarkup(one_time_keyboard=True)
    privacySelect.add(translations[lang]['privacy']['inquiry'], translations[lang]['privacy']['deletion'], translations[lang]['privacy']['exit'])
    bot.send_message(cid, translations[lang]['privacy-text'], reply_markup=privacySelect)
    userStep[cid] = 3

# inquiry or delete data
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 3)
def command_privacy2(m):
    cid = m.chat.id
    text = m.text
    lang = get_lang(cid)

    if text == translations[lang]['privacy']['inquiry']:
        try:
            bot.send_message(cid, get_user_data(cid), reply_markup=hideBoard)
            bot.send_message(cid, get_urls(cid))
        except:
            bot.send_message(cid, translations[lang]['error'], reply_markup=hideBoard)
        userStep[cid] = 0  # reset the users step back to 0

    elif text == translations[lang]['privacy']['deletion']:
        deletionSelect = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        deletionSelect.add(translations[lang]['yes'], translations[lang]['no'])
        bot.send_message(cid, translations[lang]['privacy']['sure'], reply_markup=deletionSelect)
        userStep[cid] = 4
    else:
        bot.send_message(cid, translations[lang]['privacy']['left'], reply_markup=hideBoard)
        userStep[cid] = 0

# delete data dialogue
@bot.message_handler(func=lambda message: get_user_step(message.chat.id) == 4)
def command_privacy3(m):
    cid = m.chat.id
    text = m.text
    lang = get_lang(cid)

    if text == translations[lang]['yes']:
        try:
            del_user(cid)
            bot.send_message(cid, translations[lang]['privacy']['deleted'], reply_markup=hideBoard)
        except:
            bot.send_message(cid, translations[lang]['error'], reply_markup=hideBoard)
    else:
        bot.send_message(cid, translations[lang]['privacy']['not-deleted'], reply_markup=hideBoard)
    userStep[cid] = 0


# default handler for every other text (links)
@bot.message_handler(func=lambda message: True, content_types=['text'])
def command_default(m):
    path = "user/" + str(m.chat.id)
    # Set reference path
    ref = db.reference(path)
    # Get data from database
    prov = ref.get("provider")
    tup = prov[0]
    prov = tup["provider"]
    lang = get_lang(m.chat.id)

    if prov == "isgd":
        url = ISGD.get_url() + m.text
        shorturl = get(url).json()['shorturl']

    elif prov == "vgd":
        url = VGD.get_url() + m.text
        shorturl = get(url).json()['shorturl']

    elif prov == "tiny":
        url = TINYURL.get_url() + m.text
        shorturl = get(url).text

    elif prov == "cuttly":
        url = CUTTLY.get_url() + "&short=" + m.text
        cuttly_resp = get(url).json()['url']
        status = cuttly_resp['status']

        if status == 1:
            shorturl = translations[lang]['cuttly-e1']

        # error 2: link was send without http or https
        elif status == 2:
            url2 = CUTTLY.get_url() + "http://" + m.text
            cuttly_resp2 = get(url2).json()['url']
            status2 = cuttly_resp2['status']
            shorturl = cuttly_resp2['shortLink']
            if status2 != 7:
                shorturl = translations[lang]['cuttly-e2']

        elif status == 4:
            shorturl = translations[lang]['cuttly-e4']

        elif status == 5:
            shorturl = translations[lang]['cuttly-e5']

        elif status == 6:
            shorturl = translations[lang]['cuttly-e6']

        elif status == 7:
            shorturl = cuttly_resp['shortLink']

    else:
        prov = ref.get("yourls")
        tup = prov[0]
        prov = tup["yourls"]

        url = prov + "&action=shorturl&format=json&url=" + m.text
        try:
            shorturl = get(url).json()['shorturl']
        except:
            shorturl = translations[lang]['yourls-error']

    try:
        # it replies the shortened url
        bot.send_message(m.chat.id, shorturl)
        # it saves the shortened url in the database
        save_url(m.chat.id, shorturl)
    except:
        bot.send_message(m.chat.id, translations[lang]['error'])

# function to save user in the database
def save(user):
    users_ref = ref.child('user')
    users_ref.child(str(user.id)).set({
        'provider': 'isgd',
        'yourls': 0,
        'url_count': 0,
        'urls': 0,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'lang': 'en'
    })

# function to delete user data from the database
def del_user(id):
    users_ref = ref.child('user')
    users_ref.child(str(id)).delete()
    knownUsers.remove(id)

# function to change the default url shortener in the database
def change_shortener(id, link):
    id = str(id)
    users_ref = ref.child('user')
    hopper_ref = users_ref.child(id)
    if link != "isgd" and link != "tiny" and link != "cuttly" and link != "vgd":
        hopper_ref.update({
            'provider': 'yourls',
            'yourls': link
        })

    else:
        hopper_ref.update({
            'provider': link
        })

# function for reset
def reset(id):
    id = str(id)
    users_ref = ref.child('user')
    hopper_ref = users_ref.child(id)
    hopper_ref.update({
        'yourls': '0'
    })


# function to change the language settings in the database
def change_language(id, lang):
    id = str(id)
    users_ref = ref.child('user')
    hopper_ref = users_ref.child(id)
    hopper_ref.update({
        'lang': lang
    })

# function to get the users language from the database
def get_lang(id):
    path = "user/" + str(id)
    ref = db.reference(path)
    prov = ref.get("lang")
    tup = prov[0]
    return tup["lang"]

# function to get the users yourls link
def get_yourls_link(id):
    path = "user/" + str(id)
    ref = db.reference(path)
    prov = ref.get("yourls")
    tup = prov[0]
    return tup["yourls"]


# function to get the shortened urls from a user from the database
def get_urls(id):
    id = str(id)
    lang = get_lang(id)
    # get url count
    path = "user/" + id + "/url_count"
    ref_save = db.reference(path)
    count = ref_save.get()

    mylinks = translations[lang]['mylinks']
    if count > 0:
        for el in range(count):
            child = "user/" + id + "/urls/" + str(el)
            link_ch = db.reference(child)
            mylinks += str(link_ch.get()['url']) + "\n"
        return mylinks

    else:
        return translations[lang]['mylinks-error']

# function to get the data from a user from the database
def get_user_data(id):
    lang = get_lang(id)
    path = "user/" + str(id)
    ref = db.reference(path)
    data = ref.get()

    tx = ""
    for k in translations[lang]['user']:
        tx += translations[lang]['user'][k] + ": "
        tx += str(data[k]) + "\n"
    return tx

def extract_stats(url):
    stl = []
    http = urllib.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
    try:
        response = http.request('GET', url)
        soup = BeautifulSoup(response.data, "html.parser")
        stl.append(soup.find("p").text.strip())
        stl.append(soup.find("b").text.strip())
        return stl
    except:
        stl.append(0)
        return stl

# function to save a shortened url in the database
def save_url(id, shorturl):
    id = str(id)
    # get url count
    path = "user/" + id + "/url_count"
    ref_save = db.reference(path)
    count = ref_save.get()

    # increment count
    path3 = "user/" + id
    ref_save3 = db.reference(path3)
    count_new = count + 1
    ref_save3.update({
        "url_count": count_new
    })

    #save url
    child = "user/" + id + "/urls"
    users_ref = ref.child(child)
    hopper_ref = users_ref.child(str(count))
    hopper_ref.update({
        'url': shorturl
    })

@server.route('/' + TOKEN, methods=['POST'])
def getMessage():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "!", 200

@server.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=os.environ.get('HEROKU_WEBHOOK_URL') + TOKEN)
    return "!", 200

if __name__ == "__main__":
    server.run()

# commands for local testing
#bot.remove_webhook()
#bot.polling()

# TODO: &action=version&format=json get version