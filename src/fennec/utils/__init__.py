import warnings

from datetime import datetime, timezone
from typing import List, Optional
from pyomo.environ import Var, Param, Set

warnings.filterwarnings("ignore", message="no explicit representation of timezones available for np.datetime64")


def get_utc_timestamps(start_dt: datetime, end_dt: datetime, delta_t: int):
    """

    :param start_dt: start datetime
    :param end_dt: end datetime
    :param delta_t: sample period in seconds
    :return:
    """
    return [
        start_dt.timestamp() + i * delta_t for i in range(int((end_dt - start_dt).total_seconds() / delta_t))
    ]


def convert_list_to_dict(data):
    return {i: v for i, v in enumerate(data)}

def convert_none_keys(obj):
    # If the object is a dictionary, iterate through its items
    if isinstance(obj, dict):
        new_dict = {}
        for key, value in obj.items():
            # Replace the key if it's the string "None"
            new_key = None if key == "None" else key
            # Recursively process the value
            new_dict[new_key] = convert_none_keys(value)
        return new_dict
    # If the object is a list, process each element
    elif isinstance(obj, list):
        return [convert_none_keys(item) for item in obj]
    # Return the object if it's neither a dict nor a list
    else:
        return obj


def get_detailed_results(results, instance):
    # Create a JSON-serializable dictionary from the results
    results_dict = {
        "Solver": results.solver.name,
        "Status": str(results.solver.status),
        "Termination Condition": str(results.solver.termination_condition),
    }

    records = []
    for set_i in instance.component_objects(Set, active=True):
        # Check if the variable is indexed
        try:
            for value in set_i:
                records.append({'Set': set_i.name, 'Value': value})
        except:
            continue

    results_dict["Sets"] = records

    records = []
    for var in instance.component_objects(Var, active=True):
        # Check if the variable is indexed
        try:
            if var.is_indexed():
                for index in var:
                    records.append({'Variable': var.name, 'Index': index, 'Value': var[index].value})
            else:
                records.append({'Variable': var.name, 'Index': None, 'Value': var.value})
        except:
            continue

    results_dict["Variables"] = records

    records = []
    for var in instance.component_objects(Param, active=True):
        # Check if the variable is indexed
        try:
            if var.is_indexed():
                for index in var:
                    if hasattr(var[index], 'value'):
                        records.append({'Parameter': var.name, 'Index': index, 'Value': var[index].value})
                    else:
                        records.append({'Parameter': var.name, 'Index': index, 'Value': var[index]})
            else:
                records.append({'Parameter': var.name, 'Index': None, 'Value': var.value})
        except:
            continue

    results_dict["Parameters"] = records

    # Write the dictionary to a JSON file
    return results_dict


def convert_power_to_energy(power, timestamps: Optional[List[float]]=None, delta_t: Optional[float]=None):
    """
    Convert a list of power values (in kW) and timestamps (in seconds) to energy values (in kWh).
    :param power:
    :param timestamps:
    :param delta_t:
    :return:
    """

    if timestamps is None and delta_t is None:
        raise Exception("Either timestamps or delta_t must be provided")

    if type(power) is not list:
        if delta_t is not None:
            return power * delta_t / 3600
        else:
            return power * (timestamps[1] - timestamps[0]) / 3600

    n = len(timestamps)

    delta_timestamps = [timestamps[i + 1] - timestamps[i] for i in range(n - 1)] + [
        timestamps[-1] - timestamps[-2]
    ]

    return [load_power_i * delta_timestamp_i / 3600 for delta_timestamp_i, load_power_i in zip(delta_timestamps, power)]


def get_positions_before_T(utc_timestamps, t, ref_date=None):
    """
    Returns the positions (indices) of the instants in utc_timestamps that are immediately before the
    time specified by T_str (formatted as "HH:MM") on a given reference date.

    Parameters:
        utc_timestamps (list or np.array): Array of UTC timestamps in seconds (assumed sorted).
        t (str): Time in "HH:MM" format (UTC).
        ref_date (datetime.date, optional): The reference date for t.
            If None, today's UTC date is used.

    Returns:
        List[int]: List of indices corresponding to the maximum timestamp that is less than T.
    """

    t_hour = int(t.split(":")[0])
    t_minute = int(t.split(":")[1])

    output = []
    check = 0
    for i, ts in enumerate(utc_timestamps):
        ts_hour = datetime.fromtimestamp(ts, timezone.utc).hour
        ts_minute = datetime.fromtimestamp(ts, timezone.utc).minute

        if check == 0 and (ts_hour*60 + ts_minute) > t_hour*60 + t_minute:
            if i > 0 :
                output.append(i-1)
            check = 1
        elif (ts_hour*60 + ts_minute) <= t_hour*60 + t_minute:
            check = 0

    return output



def get_is_unplugged(utc_timestamps, t_ini, t_fini):
    """
    Returns a binary vector (list of 0s and 1s) corresponding to utc_timestamps,
    where 1 indicates the timestamp is within the time window defined by T_INI and T_FINI,
    and 0 otherwise.

    Parameters:
        utc_timestamps (list): List of UTC timestamps in seconds.
        t_ini (str): Start time in "HH:MM" format (UTC).
        t_fini (str): End time in "HH:MM" format (UTC).

    Returns:
        list: Binary vector (0/1) where 1 marks timestamps within [T_INI, T_FINI].
    """

    tini_hour = int(t_ini.split(":")[0])
    tini_minute = int(t_ini.split(":")[1])
    tfini_hour = int(t_fini.split(":")[0])
    tfini_minute = int(t_fini.split(":")[1])

    output = []
    for ts in utc_timestamps:

        ts_hour = datetime.fromtimestamp(ts, timezone.utc).hour
        ts_minute = datetime.fromtimestamp(ts, timezone.utc).minute

        if (tini_hour*60 + tini_minute) <= (ts_hour*60 + ts_minute) <= (tfini_hour*60 + tfini_minute):
            output.append(1)
        else:
            output.append(0)

    return output
