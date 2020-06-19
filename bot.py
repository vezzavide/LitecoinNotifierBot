import telegram
import logging
import bitstamp.client
from telegram.ext import (Updater, CommandHandler, ConversationHandler, MessageHandler, Filters)
import pickle
import http.server
import socketserver

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


# Saves an object with the pickle module to the obj folder
def save_obj(obj, name):
    with open('obj/' + name + '.pkl', 'wb') as f:
        pickle.dump(obj, f, pickle.HIGHEST_PROTOCOL)


# Loads an onject with the pickle module from the obj folder
def load_obj(name ):
    with open('obj/' + name + '.pkl', 'rb') as f:
        return pickle.load(f)


class Bot:
    # States for subscribing operation
    SET_RANGE_AND_SUBSCRIBE = 0

    # States for changing price range operation
    CHANGE_PRICE_RANGE = 0

    def __init__(self):
        self.debug = False

        self.log("Initializing bot")
        # self.logger = logging.getLogger("litecoinbot")
        # file_logger = logging.FileHandler("bot.log")
        # file_logger.setLevel(logging.INFO)
        # file_logger.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        # self.logger.addHandler(file_logger)
        
        # TODO: insert token from command line
        self.botToken = '523550814:AAHun-6UKGr9h_33XN-Yf0G0W9P-rkIeRKw'

        # Bitstamp API polling period in seconds
        # IMPORTANT: do not exceed 1 request per second or your IP will be banned
        # (I'd say 1 request every 2 seconds is as far as you can go)
        self.bitstamp_polling_period = 5

        # This is a dictionary of dictionaries structured this way:
        # {user_id_1: {"price_range": price_range_in_float,
        #              "last_sent_price": last_sent_price_in_float},
        #  user_id_2: {"price_range": price_range_in_float,
        #              "last_sent_price": last_sent_price_in_float}
        #  ...}
        self.subscribed_users = {}

        try:
            self.subscribed_users = load_obj("subscribed_users")
        except FileNotFoundError:
            self.subscribed_users = {}

        self.updater = Updater(token=self.botToken)
        self.dispatcher = self.updater.dispatcher

        # Reboot notification
        self.startup(self.updater.bot)

        # Start command
        start_handler = CommandHandler('start', self.start)
        self.dispatcher.add_handler(start_handler)

        # current_price command
        current_ltcusd_price_handler = CommandHandler('current_price', self.current_ltcusd_price)
        self.dispatcher.add_handler(current_ltcusd_price_handler)

        # /unsubscribe command
        unsubscribe_command_handler = CommandHandler('unsubscribe', self.unsubscribe_command)
        self.dispatcher.add_handler(unsubscribe_command_handler)

        # /status command
        status_command_handler = CommandHandler('status', self.status_command)
        self.dispatcher.add_handler(status_command_handler)

        # /debug command
        debug_command_handler = CommandHandler('debug', self.debug_command, pass_args=True)
        self.dispatcher.add_handler(debug_command_handler)

        # Add conversation handler for subscribing
        subscribe_conversation_handler = ConversationHandler(
            entry_points=[CommandHandler('subscribe', self.subscribe)],
            states={
                self.SET_RANGE_AND_SUBSCRIBE: [MessageHandler(Filters.text, self.set_range_and_subscribe)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        self.dispatcher.add_handler(subscribe_conversation_handler)

        # Add conversation handler for changing price range
        set_price_range_conversation_handler = ConversationHandler(
            entry_points=[CommandHandler('change_range', self.change_price_range_command)],
            states={
                self.CHANGE_PRICE_RANGE: [MessageHandler(Filters.text, self.change_price_range)]
            },
            fallbacks=[CommandHandler('cancel', self.cancel)]
        )
        self.dispatcher.add_handler(set_price_range_conversation_handler)

        # Starts polling to Bitstamp API
        job_queue = self.updater.job_queue
        job = job_queue.run_repeating(self.litecoin_price_check, interval=5, first=0)

    def debug_command(self, bot, update, args):
        user_id = update.message.from_user.id

        if args[0] == '0':
            self.debug = False
            update.message.reply_text("Debug disabled.")
        elif args[0] == '1':
            self.debug = True
            update.message.reply_text("Debug enabled.")
        else:
            update.message.reply_text("Error: /debug argument must be either '0' or '1'")

    def startup(self, bot):
        self.log("Sending boot message to each subscribed user (if any)")
        if not self.subscribed_users:
            # No subscribed users
            return

        current_price = self.get_last_price(base='ltc', quote='usd')
        for user_id in self.subscribed_users:
            bot.send_message(chat_id=user_id,
                             text="Bot just rebooted.")
            message = "Current LTC price: *$" + "{:.2f}*".format(current_price)
            bot.send_message(chat_id=user_id, text=message, parse_mode=telegram.ParseMode.MARKDOWN)
            self.subscribed_users[user_id]["last_sent_price"] = current_price

    def status_command(self, bot, update):
        self.log_user_action(update, "Sent /status.")
        user_id = update.message.from_user.id

        if (self.subscribed_users) and (user_id in self.subscribed_users):
            message = ("You are subscribed to my alert service!\n"
                       + "Your trigger price range is currently set to ±$"
                       + str(self.subscribed_users[user_id]["price_range"])
                       + "\nSend me /change_range if you want to change it.")
        else:
            message = ("You are not subscribed to my alert service!\n"
                       + "Send /subscribe to start it.")

        update.message.reply_text(message)

    def cancel(self, bot, update):
        update.message.reply_text("Alright, action canceled.")
        return ConversationHandler.END

    def log(self, text):
        if self.debug:
            print(text)

    def log_user_action(self, update, text):
        if self.debug:
            user_id = update.message.from_user.id
            try:
                user_first_name = update.message.from_user.first_name
            except:
                user_first_name = "*no first name*"

            try:
                user_last_name = update.message.from_user.last_name
            except:
                user_last_name = "*no last name*"

            try:
                user_username = update.message.from_user.username
            except:
                user_username = "*no username*"

            print("User " + str(user_first_name)
                  + " " + str(user_last_name)
                  + " (id: " + str(user_id)
                  + " username: " + str(user_username)
                  + "): " + text)

    # /start command function
    def start(self, bot, update):
        self.log_user_action(update, "Sent /start.")
        bot.send_message(chat_id=update.message.chat_id,
                         text="Hello! I'm a Litecoin price change notifier.\n"
                              "Prices are based on the Bitstamp exchange network.\n"
                              "Send me /subscribe to start my service.")

    # Gets last price from bitstamp public api
    def get_last_price(self, base, quote):
        # TODO: maybe is not such a good idea to create an instance of Public at every call?
        # check python garbage collector
        # is this what created that weird crash?
        public_bitstamp_client = bitstamp.client.Public()
        last_price = float(public_bitstamp_client.ticker(base=base, quote=quote)['last'])
        return last_price

    # /current_price command function
    def current_ltcusd_price(self, bot, update):
        user_id = update.message.from_user.id
        current_price = self.get_last_price(base='ltc', quote='usd')
        message = "Current LTC price: *$" + "{:.2f}*".format(current_price)
        bot.send_message(chat_id=user_id, text=message, parse_mode=telegram.ParseMode.MARKDOWN)
        self.subscribed_users[user_id]["last_sent_price"] = current_price
        self.log_user_action(update, "Sent current price.")

    # /subscribe command to subscribe to the notification service
    def subscribe(self, bot, update):
        self.log_user_action(update, "Sent /subscribe.")
        user_id = int(update.message.from_user.id)

        if not (user_id in self.subscribed_users):
            update.message.reply_text("Send me the minimum price variation, in USD, that will"
                                      + " trigger your custom alerts.\n"
                                      + "Send /cancel to abort.")
            return self.SET_RANGE_AND_SUBSCRIBE

        else:
            self.log_user_action(update, "Already subscribed.")
            update.message.reply_text('You are already subscribed to my notification service!\n'
                                      + 'Your trigger price range is currently set to ±$'
                                      + str(self.subscribed_users[user_id]["price_range"])
                                      + "\nSend me /change_range if you want to change it.\n"
                                      + "Send me /unsubscribe if you want to stop the service.")
            return ConversationHandler.END

    def set_range_and_subscribe(self, bot, update):
        try:
            user_id = int(update.message.from_user.id)
            user_price_range = float(update.message.text)
            # Inserts couple {user_id: price_range} on the dictionary
            user_info = {"price_range": user_price_range,
                         "last_sent_price": self.get_last_price(base='ltc', quote='usd')}
            self.subscribed_users[user_id] = user_info

            update.message.reply_text("You successfully subscribed to my alert service!\n"
                                      + "Your trigger price range is currently set to ±$"
                                      + str(self.subscribed_users[user_id]["price_range"])
                                      + "\nSend me /change_range if you want to change "
                                      + "your trigger price range.\n"
                                      + "Send me /unsubscribe if you want to stop the service.")
            save_obj(self.subscribed_users, "subscribed_users")
            # Sends current price to user
            self.current_ltcusd_price(bot, update)
            self.log_user_action(update, "Successfully subscribed and range set to " + str(user_price_range))
        except Exception as e:
            update.message.reply_text("Something went wrong.")
            self.log_user_action(update, "Something went wrong with the subscribe process: " + e)

        return ConversationHandler.END

    # Check if ltcusd increased or decreased and if the gap is bigger than notification_price_range, subscribed users
    # are notified
    def litecoin_price_check(self, bot, job):
        self.log("Checking litecoin price for each user...")

        try:
            current_litecoin_price = self.get_last_price(base='ltc', quote='usd')
            for user_id in self.subscribed_users:
                price_difference = current_litecoin_price - self.subscribed_users[user_id]["last_sent_price"]
                price_range = self.subscribed_users[user_id]["price_range"]

                if price_difference > price_range:
                    # Relevant increment
                    self.log("Increment to "
                          + str(current_litecoin_price)
                          + " for user " + str(user_id))

                    text = "LTC price increased: *$" + "{:.2f}*".format(current_litecoin_price) + " ⬆"
                    bot.send_message(chat_id=user_id, text=text, parse_mode=telegram.ParseMode.MARKDOWN)
                    self.subscribed_users[user_id]["last_sent_price"] = current_litecoin_price
                elif price_difference < -price_range:
                    # Relevant decrement
                    self.log("Decrement to "
                          + str(current_litecoin_price)
                          + " for user " + str(user_id))
                    text = "LTC price decreased: *$" + "{:.2f}*".format(current_litecoin_price) + " ⬇"
                    bot.send_message(chat_id=user_id, text=text, parse_mode=telegram.ParseMode.MARKDOWN)
                    self.subscribed_users[user_id]["last_sent_price"] = current_litecoin_price

        except Exception as e:
            self.log("Error in litecoin_price_check!" + e)

    def change_price_range_command(self, bot, update):
        self.log_user_action(update, "Sent /change_range.")
        user_id = update.message.from_user.id
        if (self.subscribed_users) and (user_id in self.subscribed_users):
            update.message.reply_text("Alright, send me your new trigger range in USD.\n"
                                    + "Send /cancel to abort.")
            return self.SET_RANGE_AND_SUBSCRIBE
        else:
            # User is not subscribed yet
            update.message.reply_text("You're not subscribed yet!\n"
                                      "Send /subscribe to subscribe to my service.")
            return ConversationHandler.END

    # Changes price_range for current user
    def change_price_range(self, bot, update):
        try:
            user_id = update.message.from_user.id
            price_range = float(update.message.text)
            self.subscribed_users[user_id]["price_range"] = price_range
            update.message.reply_text("You successfully changed your trigger range to ±$"
                                      + "{:.2f}".format(price_range))
            # Saves users dict
            save_obj(self.subscribed_users, "subscribed_users")

            self.log_user_action(update, "Successfully changed his price range to " + str(price_range))

            # Sends current price to user
            self.current_ltcusd_price(bot, update)
        except Exception:
            self.log_user_action(update, "Something went wrong with the change price range process.")
            update.message.reply_text("Something went wrong.")

        return ConversationHandler.END

    def unsubscribe_command(self, bot, update):
        self.log_user_action(update, "Sent /unsubscribe")
        user_id = update.message.from_user.id
        del self.subscribed_users[user_id]
        update.message.reply_text("You successfully unsubscribed to my alert service!\n"
                                  + "Send /subscribe to start again.")
        self.log_user_action(update, "Unsubscribed")

    def run(self):
        self.updater.start_polling()
        return


if __name__ == '__main__':
    bot = Bot()
    bot.run()

    PORT = 8000
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("serving at port", PORT)
        httpd.serve_forever()
