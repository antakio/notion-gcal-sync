from __future__ import print_function
import datetime
from dateutil import tz
from dateutil.parser import parse
import pickle
import os
import pytz
import inspect
import time
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from notion.client import NotionClient
from notion.collection import NotionDate

import config as CONFIG

# If modifying these scopes, delete the file token.pickle.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def gcal_auth():
    global creds
    """Shows basic usage of the Google Calendar API.
    Prints the start and name of the next 10 events on the user"s calendar.
    """
    creds = None
    # The file token.pickle stores the user"s access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            filename = "credentials.json"
            flow = InstalledAppFlow.from_client_secrets_file(
                filename, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    main()


def main():

    # PREP DATA
    # ====================================================================================================
    global creds
    global google_calendar_ids
    global timezone
    global notion_table
    global notion_date_prop
    global notion_cal_prop
    global notion_del_prop

    # Number of days, from events would be loaded (0 - all)
    google_calendar_ids = {}
    notion_token_v2 = CONFIG.notion_token_v2
    notion_table = CONFIG.notion_table
    notion_date_prop = CONFIG.notion_date_prop
    notion_cal_prop = CONFIG.notion_cal_prop
    notion_del_prop = CONFIG.notion_del_prop
    debug = False

    last_sync = convert_datetime_timezone(datetime.datetime.utcnow() - datetime.timedelta(minutes=10), 'UTC', 'UTC')

    while(not False):
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        api_loaded = False
        try:
            service = build('calendar', 'v3', credentials=creds)
            client = NotionClient(token_v2=notion_token_v2)
            api_loaded = True
        except Exception as e:
            print(
                f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))

        if(api_loaded):
            # Call the Google API
            # ====================================================================================================
            google_res = {}

            page_token = None
            while True:
                calendar_list = service.calendarList().list(pageToken=page_token).execute()
                for calendar_list_entry in calendar_list['items']:
                    google_calendar_ids[calendar_list_entry['summary']] = calendar_list_entry['id']
                page_token = calendar_list.get('nextPageToken')
                if not page_token:
                    break

            # get gcal recent rows by each calendar
            try:
                for calendar_name, calendar_id in google_calendar_ids.items():
                    events_result = service.events().list(calendarId=calendar_id,
                                                          updatedMin=((str(last_sync).replace(" ", "T").split('.')[0]) + "Z"),
                                                          singleEvents=True,
                                                          orderBy="startTime",
                                                          showDeleted=True).execute()
                    google_res[calendar_name] = events_result.get("items", [])
            except Exception as e:
                print(
                    f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))

            google_events = []
            for cal_name, res_events in google_res.items():
                for gevent in res_events:
                    new_event = google_ev_format(service,gevent=gevent)
                    google_events.append(new_event)

            google_events_ids = [x['id'] for x in google_events]
            if debug:
                print(f"[{datetime.datetime.now()}] " +
                      "Google events amount:" + str(len(google_events_ids)))

            # Call the Notion API
            # ====================================================================================================

            cv = client.get_collection_view(notion_table)

            # Run a "sorted" query (inspect network tab in browser for examples, on queryCollection calls)

            sort_params = [{
                "direction": "descending",
                "property": "Lmsz",
            }]

            # get rows from notion table
            notion_res = {}
            try:
                notion_res = cv.build_query(sort=sort_params).execute()
                #notion_res = cv.collection.get_rows()
            except Exception as e:
                print(
                    f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))

            notion_events = []
            for nevent in notion_res:
                new_event = notion_ev_format(nevent=nevent)
                if (new_event["updated"] > last_sync):
                    notion_events.append(new_event)

            notion_events_ids = [x["id"] for x in notion_events]
            if debug:
                print(f"[{datetime.datetime.now()}] " +
                      "Notion events amount:" + str(len(notion_events_ids)))

            # SORT DATA
            # ====================================================================================================
            add_to_notion = []  # gev.id not in nevs
            add_to_google = []  # nev.id not in gevs and nev.start not null and     nev.cal not null
            update_in_notion = []  # nev.id == gev.id and gev.upd < nev.upd
            update_in_google = []  # gev.id == nev.id and gev.upd > nev.upd
            # nev.id == gev.id and gev.stat == canceled and gev.upd > nev.upd
            delete_from_notion = []
            # nev.id == gev.id and nev.stat == canceled and gev.upd < nev.upd
            delete_from_google = []
            restore_from_google = []
            restore_from_notion = []

            for nev in notion_events:
                gev = google_ev_search(service, nev)

                if(gev == None):
                    if (nev["start"] != None and nev["calendar"] != None and not nev["deleted"]):
                        print(f"[{datetime.datetime.now()}] " +
                              f"GOOGLE MISSING EVENT - {nev['calendar']} | [{nev['title']}] | {nev['start']} -> {nev['end']}")
                        add_to_google.append(nev)
                else:
                    gev = google_ev_format(service, gev)
                    if (not gev["deleted"] and not nev["deleted"]):
                        if compare_evs(nev, gev):
                            if(nev["updated"] > gev["updated"]):
                                update_in_google.append(nev)
                    else:
                        if (nev["deleted"] == True and gev["deleted"] == False and nev["updated"] > gev["updated"]):
                            print(f"[{datetime.datetime.now()}] " +
                                  f"GOOGLE EVENT TO DELETE - {nev['calendar']} | [{nev['title']}] | {nev['start']} -> {nev['end']}")
                            delete_from_google.append(nev)
                        if (nev["deleted"] == False and gev["deleted"] == True) and (nev["updated"] > gev["updated"]):
                            print(f"[{datetime.datetime.now()}] " +
                                  f"GOOGLE EVENT TO RESTORE - {nev['calendar']} | [{nev['title']}] | {nev['start']} -> {nev['end']}")
                            restore_from_google.append(nev)

            for gev in google_events:
                nev = notion_ev_search(client, gev)

                if nev is None:
                    if (gev["start"] != None and gev["calendar"] != None and not gev["deleted"]):
                        print(f"[{datetime.datetime.now()}] " +
                              f"NOTION MISSING EVENT - {gev['calendar']} | [{gev['title']}] | {gev['start']} -> {gev['end']}")
                        add_to_notion.append(gev)
                else:
                    nevf = notion_ev_format(nev)
                    if (not gev["deleted"] and not nevf["deleted"]):
                        if compare_evs(nevf, gev):
                            if(gev["updated"] > nevf["updated"]):
                                update_in_notion.append(gev)
                    else:
                        if (nevf["deleted"] == False and gev["deleted"] == True and gev["updated"] > nevf["updated"]):
                            print(f"[{datetime.datetime.now()}] " +
                                  f"NOTION EVENT TO DELETE - {gev['calendar']} | [{gev['title']}] | {gev['start']} -> {gev['end']}")
                            delete_from_notion.append(nev)
                        if (nevf["deleted"] == True and gev["deleted"] == False) and (gev["updated"] > nevf["updated"]):
                            print(f"[{datetime.datetime.now()}] " +
                                  f"NOTION EVENT TO RESTORE - {gev['calendar']} | [{gev['title']}] | {gev['start']} -> {gev['end']}")
                            restore_from_notion.append(nev)

            if debug:
                print(f"[{datetime.datetime.now()}] " +
                      "Add to Google: " + str(len(add_to_google)))
                print(f"[{datetime.datetime.now()}] " +
                      "Add to Notion: " + str(len(add_to_notion)))
                print(f"[{datetime.datetime.now()}] " +
                      "Update in Google: " + str(len(update_in_google)))
                print(f"[{datetime.datetime.now()}] " +
                      "Update in Notion: " + str(len(update_in_notion)))
                print(f"[{datetime.datetime.now()}] " +
                      "Delete from Google: " + str(len(delete_from_google)))
                print(f"[{datetime.datetime.now()}] " +
                      "Delete from Notion: " + str(len(delete_from_notion)))
                print(f"[{datetime.datetime.now()}] " +
                      "Restore from Google: " + str(len(restore_from_google)))
                print(f"[{datetime.datetime.now()}] " +
                      "Restore from Notion: " + str(len(restore_from_notion)))

            # SYNC DATA
            # ====================================================================================================

            # TODO: How to find in this NotionCollection

            for event in add_to_notion:
                new_event = notion_add_event(cv, service, event)
                if new_event:
                    new_event = notion_ev_format(new_event)
                    print(f"[{datetime.datetime.now()}] " +
                          f"ADDED | NOTION {new_event['calendar']} | [{new_event['title']}] | {new_event['start']} -> {new_event['end']}")

            for event in add_to_google:
                new_event = google_add_event(service, event)
                if new_event:
                    new_event = google_ev_format(service, new_event)
                    print(f"[{datetime.datetime.now()}] " +
                          f"ADDED | GOOGLE {new_event['calendar']} | [{new_event['title']}] | {new_event['start']} -> {new_event['end']}")

            for nevupd in update_in_notion:
                nev = notion_ev_search(client, nevupd)
                new_event = notion_update_event(nev, nevupd)
                if new_event:
                    new_event = notion_ev_format(new_event)
                    print(f"[{datetime.datetime.now()}] " +
                          f"UPDATED | NOTION {new_event['calendar']} | [{new_event['title']}] | {new_event['start']} -> {new_event['end']}")

            for gevupd in update_in_google:
                gev = google_ev_search(service, gevupd)

                new_event = google_update_event(service, gev, gevupd)
                if new_event:
                    new_event = google_ev_format(service, new_event)
                    print(f"[{datetime.datetime.now()}] " +
                          f"UPDATED | GOOGLE {new_event['calendar']} | [{new_event['title']}] | {new_event['start']} -> {new_event['end']}")

            for gevdel in delete_from_google:
                res = google_delete_event(service, gevdel)
                if res:
                    print(f"[{datetime.datetime.now()}] " +
                          f"DELETED | GOOGLE {gevdel['calendar']} | [{gevdel['title']}] | {gevdel['start']} -> {gevdel['end']}")

            for nevdel in delete_from_notion:
                res = notion_delete_event(nevdel)
                if res:
                    nevdel = notion_ev_format(nevdel)
                    print(f"[{datetime.datetime.now()}] " +
                          f"DELETED | NOTION {nevdel['calendar']} | [{nevdel['title']}] | {nevdel['start']} -> {nevdel['end']}")

            for gevres in restore_from_google:
                res = google_restore_event(service, gevres)
                if res:
                    res = google_ev_format(service, res)
                    print(f"[{datetime.datetime.now()}] " +
                          f"RESTORED | GOOGLE {res['calendar']} | [{res['title']}] | {res['start']} -> {res['end']}")

            for nevres in restore_from_notion:
                res = notion_restore_event(nevres)  
                if res:
                    res = notion_ev_format(res)
                    print(f"[{datetime.datetime.now()}] " +
                          f"RESTORED | NOTION {res['calendar']} | [{res['title']}] | {res['start']} -> {res['end']}")

            last_sync = convert_datetime_timezone(datetime.datetime.utcnow() - datetime.timedelta(minutes=10), 'UTC', 'UTC')
            time.sleep(70)


def notion_ev_format(nevent):

    new_event = {}
    new_event["id"] = nevent.id.replace("-", "00a00")
    new_event["title"] = nevent.name

    # new_event Target_Date  = nevent Target Date
    if getattr(nevent, notion_date_prop) == None:
        new_event["start"] = None
        new_event["end"] = None
        new_event["timezone"] = None
    else:
        new_event["start"] = getattr(
            getattr(nevent, notion_date_prop), "start")
        new_event["end"] = getattr(getattr(nevent, notion_date_prop), "end")
        new_event["timezone"] = getattr(getattr(nevent, notion_date_prop), "timezone")

        # date/datetime, None
        if new_event["end"] == None:
            # date1, None
            if isinstance(new_event["start"], datetime.date):
                a = 'a'
            # datetime1, None
            else:
                b = 'b'

        # date/datetime, date/datetime
        else:
            # date, date
            if isinstance(new_event["start"], datetime.date):
                # date1, date1
                if (new_event["start"] == new_event["end"]):
                    new_event["end"] = None
                # date1, date2
            # datetime, datetime
            else:
                # datetime1, datetime1
                delta_minutes = (new_event["end"] -
                                 new_event["start"]).seconds / 60
                if (new_event["start"] == new_event["end"] or delta_minutes <= 15):
                    new_event["end"] = None
                # datetime1, datetime2

    if(new_event["start"]):
        new_event["start"] = convert_datetime_timezone(new_event["start"], new_event["timezone"], 'UTC')
    if(new_event["end"]):
        new_event["end"] = convert_datetime_timezone(new_event["end"], new_event["timezone"], 'UTC')

    if not hasattr(nevent, notion_cal_prop):
        new_event["calendar"] = ""
    else:
        new_event["calendar"] = getattr(nevent, notion_cal_prop)

    # TODO TZ FORMAT
    new_event["updated"] = convert_datetime_timezone(nevent.Last_Edited,'UTC','UTC')
    deleted = getattr(nevent, notion_del_prop)

    if deleted == False or deleted == '' or deleted == None:
        new_event["deleted"] = False
    else:
        new_event["deleted"] = True

    return new_event

def google_ev_format(service, gevent):

    if "description" not in gevent:
        gevent["description"] = ""
    if "summary" not in gevent:
        gevent["summary"] = ""
    new_event = {}
    new_event["id"] = gevent["id"]
    new_event["title"] = gevent["summary"]
    new_event["description"] = gevent["description"]

    # datetime1, datetime2
    new_event["start"] = parse(gevent["start"]["dateTime"])
    new_event["end"] = parse(gevent["end"]["dateTime"])

    if "timeZone" in gevent["start"]:
        new_event["timezone"] = gevent["start"]["timeZone"]
    else:
        try:
            calendar = service.calendars().get(calendarId=gevent['organizer']['email']).execute()
            new_event["timezone"] = calendar["timeZone"]
        except Exception as e:
            print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))

    new_event["start"] = convert_datetime_timezone(new_event["start"],  new_event["timezone"], 'UTC')
    new_event["end"] = convert_datetime_timezone(new_event["end"],  new_event["timezone"], 'UTC')

    # all day events
    if (new_event["start"].hour == 0 and new_event["start"].minute == 0
            and new_event["end"].hour == 0 and new_event["end"].minute == 0):
        days_delta = (new_event["end"] - new_event["start"]).days
        if(days_delta > 1):
            new_event["start"] = datetime.date(
                new_event["start"].year, new_event["start"].month, new_event["start"].day)
            new_event["end"] = datetime.date(
                new_event["end"].year, new_event["end"].month, new_event["end"].day)
        # date1, date1 + 1
        if(days_delta == 1):
            new_event["start"] = datetime.date(
                new_event["start"].year, new_event["start"].month, new_event["start"].day)
            new_event["end"] = None
        # date1, date1
        if(new_event["start"] == new_event["end"]):
            new_event["start"] = datetime.date(
                new_event["start"].year, new_event["start"].month, new_event["start"].day)
            new_event["end"] = None

        # date1, date2

    else:
        # datetime1, datetime1
        delta_minutes = (new_event["end"] - new_event["start"]).seconds / 60
        if (new_event["start"] == new_event["end"] or delta_minutes <= 15):
            new_event["end"] = None
        # datetime1, datetime2

    new_event["updated"] = parse(gevent["updated"].split('.')[0])
    new_event["updated"] = convert_datetime_timezone(new_event["updated"],'UTC','UTC')
    if "organizer" in gevent:
        new_event["calendar"] = gevent['organizer']['displayName']
    else:
        new_event["calendar"] = ''
    if gevent["status"] == "cancelled":
        new_event["deleted"] = True
    else:
        new_event["deleted"] = False

    return new_event

def compare_evs(nev, gev):
    ev_update = False
    field = "title"
    if(gev[field] != nev[field]):
        print(f"[{datetime.datetime.now()}] " +
              f"CHANGES FOUNDED - [{gev['title']}] | [{field}] N {nev[field]} != G {gev[field]}")
        ev_update = True
    field = "start"
    if(gev[field] != nev[field]):
        print(f"[{datetime.datetime.now()}] " +
              f"CHANGES FOUNDED - [{gev['title']}] | [{field}] N {nev[field]} != G {gev[field]}")
        ev_update = True
    field = "end"
    if(gev[field] != nev[field]):
        print(f"[{datetime.datetime.now()}] " +
              f"CHANGES FOUNDED - [{gev['title']}] | [{field}] N {nev[field]} != G {gev[field]}")
        ev_update = True
    field = "calendar"
    if(gev[field] != nev[field]):
        print(f"[{datetime.datetime.now()}] " +
              f"CHANGES FOUNDED - [{gev['title']}] | [{field}] N {nev[field]} != G {gev[field]}")
        ev_update = True
    return ev_update

def notion_add_event(notion_client, google_client, event):

    n_date = NotionDate(convert_datetime_timezone(event["start"], 'UTC', event['timezone']))
    n_date.end = convert_datetime_timezone(event["end"], 'UTC', event['timezone'])
    n_date.timezone = event["timezone"]
    
    try:
        notion_event = notion_client.collection.add_row()
        notion_event.name = event["title"]
        setattr(notion_event, notion_date_prop, n_date)
        setattr(notion_event, notion_cal_prop, event["calendar"])

        print(f"[{datetime.datetime.now()}] N ADD DONE {event['title']}")

    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    nevent_id = str(notion_event.id.replace("-", "00a00"))
    event_body = google_client.events().get(calendarId=google_calendar_ids[event["calendar"]],
                                            eventId=event["id"]).execute()

    event_body["id"] = nevent_id
    del event_body["iCalUID"]
    if 'recurringEventId' in event_body:
        del event_body['recurringEventId']

    try:
        google_client.events().delete(calendarId=google_calendar_ids[event["calendar"]],
                                      eventId=event["id"]).execute()
        event_body_new = google_client.events().insert(
            calendarId=google_calendar_ids[event["calendar"]], body=event_body).execute()
        print(f"[{datetime.datetime.now()}] N ADD (G ID) DONE {event['title']}")
    except Exception as e:
        # notion_delete_event(notion_event)
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    return notion_event

def google_ev_search(google_client, _event):
    result = None

    try:
        result = google_client.events().get(
            calendarId=google_calendar_ids[_event['calendar']], eventId=_event['id'], showdeleted=True).execute()
        if result != None:
            return result
    except Exception as e:
        result = None

    for calendar in google_calendar_ids.values():
        try:
            result = google_client.events().get(
                calendarId=calendar, eventId=_event['id']).execute()
            if result != None:
                break
        except Exception as e:
            result = None

    return result

def notion_ev_search(notion_client, _event):
    result = None
    try:
        result = notion_client.get_block(_event['id'].replace("00a00", "-"))
    except Exception as e:
        return None
    return result

def google_add_event(google_client, _event):

    # 1 date - x - All day event -> start 0 0 start+1d 0 0
    # 2 date - date - Many days event -> start end
    # 3 datetime - x - Not impossible with google events -> start start
    # 4 datetime - datetime - regular -> start start

    start = ""
    end = ""
    key = ""
    # 1 3
    if _event["end"] == None:
        # 1
        if (isinstance(_event["start"], datetime.date)):
            start = datetime.date(
                _event["start"].year, _event["start"].month, _event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["start"] + datetime.timedelta(minutes=15)
            key = "dateTime"
    # 2 4
    else:
        # 2
        if (isinstance(_event["start"], datetime.date)):
            start = _event["start"]
            end = _event["end"]
            key = "date"
        # 4
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["end"]
            key = "dateTime"

    start = str(start).replace(" ", "T")
    end = str(end).replace(" ", "T")

    event_body = {
        "end": {
            key: end,
            "timeZone": _event["timezone"]
        },
        "start": {
            key: start,
            "timeZone": _event["timezone"]
        },
        "summary": _event["title"],
        "id": _event["id"]
    }
    try:
        event = google_client.events().insert(
            calendarId=google_calendar_ids[_event["calendar"]], body=event_body).execute()
        event = google_client.events().update(calendarId=google_calendar_ids[_event["calendar"]],
                                              eventId=_event["id"], body=event).execute()
        print(f"[{datetime.datetime.now()}] G ADD DONE {_event['title']}")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    return event

def notion_update_event(notion_event, event):
    n_date = None

    # date - x - All day event
    # date - date - Many days event`
    # datetime - x - Not impossible with google events
    # datetime - datetime - regular

    n_date = NotionDate(convert_datetime_timezone(event["start"], 'UTC', event['timezone']))
    n_date.end = convert_datetime_timezone(event["end"], 'UTC', event['timezone'])
    n_date.timezone = event["timezone"]

    try:
        notion_event.name = event["title"]
        setattr(notion_event, notion_date_prop, n_date)
        setattr(notion_event, notion_cal_prop, event["calendar"])
        print(f"[{datetime.datetime.now()}] N UPDATE DONE {event['title']}")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    return notion_event

def google_update_event(google_client, gevent, _event):

    # 1 date - x - All day event -> start 0 0 start+1d 0 0
    # 2 date - date - Many days event -> start end
    # 3 datetime - x - Not impossible with google events -> start start
    # 4 datetime - datetime - regular -> start start

    start = ""
    end = ""
    key = ""
    # 1 3
    if _event["end"] == None:
        # 1
        if (isinstance(_event["start"], datetime.date)):
            start = datetime.date(
                _event["start"].year, _event["start"].month, _event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["start"] + datetime.timedelta(minutes=15)
            key = "dateTime"
    # 2 4
    else:
        # 2
        if (isinstance(_event["start"], datetime.date)):
            start = _event["start"]
            end = _event["end"]
            key = "date"
        # 4
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["end"]
            key = "dateTime"

    start = str(start).replace(" ", "T")
    end = str(end).replace(" ", "T")

    event_body = {
        "end": {
            key: end,
            "timeZone": _event["timezone"]
        },
        "start": {
            key: start,
            "timeZone": _event["timezone"]
        },
        "summary": _event["title"],
        "id": _event["id"]
    }

    gev = google_ev_format(gevent)

    if (_event["calendar"] != gev["calendar"]):
        try:
            # make old id free
            event = google_client.events().move(calendarId=google_calendar_ids[gev["calendar"]],
                                                  eventId=(gev["id"]),  destination=google_calendar_ids[_event["calendar"]]).execute()
            event = google_client.events().update(calendarId=google_calendar_ids[_event["calendar"]],
                                                  eventId=_event["id"], body=event_body).execute()
            print(f"[{datetime.datetime.now()}] G UPDATE DONE {_event['title']}")
        except Exception as e:
            print(
                f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
            return None
    else:
        try:
            event = google_client.events().update(calendarId=google_calendar_ids[gev["calendar"]],
                                                  eventId=_event["id"], body=event_body).execute()
            print(f"[{datetime.datetime.now()}] G UPDATE DONE {_event['title']}")
        except Exception as e:
            print(
                f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
            return None

    return event

def google_restore_event(google_client, _event):

   # 1 date - x - All day event -> start 0 0 start+1d 0 0
    # 2 date - date - Many days event -> start end
    # 3 datetime - x - Not impossible with google events -> start start
    # 4 datetime - datetime - regular -> start start

    start = ""
    end = ""
    key = ""
    # 1 3
    if _event["end"] == None:
        # 1
        if (isinstance(_event["start"], datetime.date)):
            start = datetime.date(
                _event["start"].year, _event["start"].month, _event["start"].day)
            end = (start + datetime.timedelta(days=1))
            key = "date"
        # 3
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["start"] + datetime.timedelta(minutes=15)
            key = "dateTime"
    # 2 4
    else:
        # 2
        if (isinstance(_event["start"], datetime.date)):
            start = _event["start"]
            end = _event["end"]
            key = "date"
        # 4
        if (isinstance(_event["start"], datetime.datetime)):
            start = _event["start"]
            end = _event["end"]
            key = "dateTime"

    start = str(start).replace(" ", "T")
    end = str(end).replace(" ", "T")

    event_body = {
        "end": {
            key: end,
            "timeZone": _event["timezone"]
        },
        "start": {
            key: start,
            "timeZone": _event["timezone"]
        },
        "summary": _event["title"],
        "id": _event["id"],
        "status": "confirmed"
    }

    try:
        event = google_client.events().update(calendarId=google_calendar_ids[_event["calendar"]],
                                              eventId=_event["id"], body=event_body).execute()
        print(f"[{datetime.datetime.now()}] G RESTORE DONE {_event['title']}")
    except Exception as e:
        print(
            f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    return event

def google_delete_event(google_client, _event):
    try:
        event = google_client.events().delete(calendarId=google_calendar_ids[_event["calendar"]],
                                              eventId=_event["id"]).execute()
        print(f"[{datetime.datetime.now()}] " +
              f"G DELETE DONE {_event['title']}")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return False
    return True

def notion_delete_event(nev):

    try:
        if (not hasattr(nev, notion_del_prop)): 
            setattr(nev, notion_del_prop, "Deleted by google")
            print(f"[{datetime.datetime.now()}] " +
                    f"N DELETE DONE {nev.title}")
        else:
            if getattr(nev, notion_del_prop) == False:
                setattr(nev, notion_del_prop, True)
                print(f"[{datetime.datetime.now()}] " +
                    f"N DELETE DONE {nev.title}")

    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return False
    return True

def notion_restore_event(event):

    try:
        setattr(event, notion_del_prop, '')
        print(f"[{datetime.datetime.now()}] N RESTORE DONE {event['title']}")
    except Exception as e:
        print(f"[{datetime.datetime.now()}] | {str(inspect.stack()[0][3])} " + str(e))
        return None

    return event

def convert_datetime_timezone(dt, tz1, tz2):
    
    if(not tz1 and not tz2):
        tz1 = 'UTC'
        tz2 = 'UTC'
    if (isinstance(dt,datetime.datetime)):
        if dt.tzinfo is None:
            tz1 = pytz.timezone(tz1)
            dt = tz1.localize(dt)
        tz2 = pytz.timezone(tz2)
        dt = dt.astimezone(tz2)

    return dt

if __name__ == "__main__":
    if os.path.exists('token.pickle'):
        main()
    else:
        gcal_auth()
