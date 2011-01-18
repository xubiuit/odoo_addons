# -*- encoding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution    
#    Copyright (C) 2010 Smile (<http://www.smile.fr>). All Rights Reserved
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from osv import fields, osv, orm
import service
import netsvc
import pooler
import re
import time
from mx.DateTime import RelativeDateTime, now
import tools
from tools.translate import _
import traceback
import inspect
import operator

def _get_browse_record_dict(self, cr, uid, ids):
    """Get a dictionary of dictionary from browse records list"""
    if isinstance(ids, (int, long)):
        ids = [ids]
    return dict([(object.id, dict([(field, eval('obj.' + field, {'obj':object})) for field in self._columns])) for object in self.browse(cr, uid, ids)])

class ir_model_methods(osv.osv):
    _name = 'ir.model.methods'
    _description = 'Model Method'

    _columns = {
        'name': fields.char('Method name', size=128, select=True, required=True),
        'model_id': fields.many2one('ir.model', 'Object', select=True, required=True),
    }
ir_model_methods()

class sartre_operator(osv.osv):
    _name = 'sartre.operator'
    _description = 'Sartre Operator'

    def __init__(self, pool, cr):
        super(sartre_operator, self).__init__(pool, cr)
        cr.execute("SELECT * FROM pg_class WHERE relname=%s", (self._table,))
        if cr.rowcount:
            self._update_operators_cache(cr)

    _columns = {
        'name': fields.char('Name', size=30, required=True),
        'symbol': fields.char('Symbol', size=8, required=True),
        'opposite_symbol': fields.char('Opposite symbol', size=12, help="Opposite symbol for SQL filter"),
        'value_age_filter': fields.selection([('current', 'Current'), ('old', 'Old'), ('both', 'Both')], 'Value Age Filter', required=True),
        'native_operator': fields.selection([('=', 'is equal to'), ('<=', 'less than'), ('>=', 'greater than'), ('like', 'contains'),
                                             ('ilike', 'contains exactly'), ('in', 'in'), ('child_of', 'child of'), ('none', 'none')], 'Native Operator'),
        'other_value_necessary': fields.boolean('Other Value Necessary'),
        'other_value_transformation': fields.char('Value Transformation', size=64, help="Useful only for native operator"),
        'expression': fields.text('Expression'),
    }

    _defaults = {
        'native_operator': lambda * a: 'none',
        'value_age_filter': lambda * a: 'both',
        'expression': lambda * a: """# You can use the following variables
\n#    - selected_field_value (current or old value according to the value age choosed by the user - value age filter == 'Both')
\n#    - current_field_value (useful if value age filter != 'Both')
\n#    - old_field_value (useful if value age filter != 'Both')
\n#    - other_value (static or dynamic)
\n# You must assign a boolean value to the variable "result"
""",
        'other_value_necessary': lambda * a: False,
    }

    def _update_operators_cache(self, cr):
        operator_ids = self.search(cr, 1, [])
        operators = self.browse(cr, 1, operator_ids)
        self.sartre_operators_cache = dict([(item.symbol, item) for item in operators])
        opposite_operators_dict = dict([(item.opposite_symbol, item) for item in operators])
        self.sartre_operators_cache.update(opposite_operators_dict)
        return True

    def sartre_operator_decorator(fnct):
        def new_fnct(self, cr, *args, **kwds):
            result = getattr(osv.osv, fnct.__name__)(self, cr, *args, **kwds)
            if result:
                self._update_operators_cache(cr)
            return result
        return new_fnct

    @sartre_operator_decorator
    def create(self, cr, uid, vals, context={}):
        return super(sartre_operator, self).create(cr, uid, vals, context)

    @sartre_operator_decorator
    def write(self, cr, uid, ids, vals, context={}):
        return super(sartre_operator, self).write(cr, uid, ids, vals, context)

    @sartre_operator_decorator
    def unlink(self, cr, uid, ids, context={}):
        return super(sartre_operator, self).unlink(cr, uid, ids, context)

sartre_operator()

class sartre_trigger(osv.osv):
    _name = 'sartre.trigger'
    _description = 'Sartre Trigger'
    logger = netsvc.Logger()

    def __init__(self, pool, cr):
        super(sartre_trigger, self).__init__(pool, cr)
        cr.execute("SELECT * FROM pg_class WHERE relname=%s", (self._table,))
        if cr.rowcount:
            self._update_triggers_cache(cr)

    def _get_trigger_date_type(self, cr, uid, ids, name, args, context={}):
        """Get trigger date type"""
        res = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        for trigger in self.browse(cr, uid, ids):
            if trigger.on_date_type_display1 == 'other_date':
                res[trigger.id] = trigger.on_date_type_display2_id.name
            else:
                res[trigger.id] = trigger.on_date_type_display1
        return res

    def onchange_get_domain_force(self, cr, uid, ids, filter_ids, domain_force, context={}):
        """Build domain expression from filters"""
        res = {}
        domain_force = domain_force and eval(domain_force) or []
        for filter in self.pool.get('sartre.filter').read(cr, uid, filter_ids, ['domain']):
            domain_force.exparent.tend(filter['domain'] and eval(filter['domain']) or [])
        res.setdefault('value', {})['domain_force'] = domain_force
        return res

    def onchange_model_id(self, cr, uid, ids, model_id, on_function, on_other, context={}):
        """Dynamic domain for the field on_function_field_id"""
        res = {'value': {}}
        if model_id:
            model = self.pool.get('ir.model').read(cr, uid, model_id, ['model'])['model']
            obj = self.pool.get(model)
            if on_function:
                function_fields = [field for field in obj._columns if isinstance(obj._columns[field], (fields.function, fields.related, fields.property))]
                res.setdefault('domain', {})['on_function_field_id'] = "[('model_id', '=', %s),('name', 'in', %s)]" % (model_id, map(str, function_fields))
            if on_other:
                method_names = [attr for attr in dir(obj.__class__) if inspect.ismethod(getattr(obj, attr))]
                model_methods_pool = self.pool.get('ir.model.methods')
                model_methods_ids = model_methods_pool.search(cr, uid, [('model_id', '=', model_id), ('name', 'in', method_names)])
                existing_method_names = [method['name'] for method in model_methods_pool.read(cr, uid, model_methods_ids, ['name'])]
                for method in method_names:
                    method_args = inspect.getargspec(getattr(obj, method))[0]
                    if method not in ['create', 'write', 'unlink'] + existing_method_names and not method.startswith('__') and ('ids' in method_args or 'id' in method_args):
                        model_methods_pool.create(cr, uid, {'name': method, 'model_id': model_id})
        return res

    _columns = {
        'name': fields.char("Name", size=64, required=True),
        'model_id': fields.many2one('ir.model', 'Object', domain=[('osv_memory', '=', False)], required=True, ondelete='cascade'),
        'active': fields.boolean("Active"),
        'on_create': fields.boolean("Creation"),
        'on_write': fields.boolean("Update"),
        'on_unlink': fields.boolean("Deletion"),
        'on_function': fields.boolean("Function"),
        'on_function_type': fields.selection([('set', 'Manually'), ('get', 'Automatically'), ('both', 'Both')], "updated", size=16),
        'on_function_field_id': fields.many2one('ir.model.fields', "Function field", domain="[('model_id', '=', model_id)]", help="Function, related or property field"),
        'on_other': fields.boolean("Other method", help="Only methods with an argument 'id' or 'ids' in their signatures"),
        'on_other_method_id': fields.many2one('ir.model.methods', "Object method", domain="[('model_id', '=', model_id)]"),
        'on_date': fields.boolean("Date"),
        'on_date_type': fields.function(_get_trigger_date_type, method=True, type='char', size=64, string='Trigger Date Type', store=True),
        'on_date_type_display1': fields.selection([('create_date', 'Creation Date'), ('write_date', 'Update Date'), ('other_date', 'Other Date')], 'Trigger Date Type 1', size=16),
        'on_date_type_display2_id': fields.many2one('ir.model.fields', 'Trigger Date Type 2', domain="[('ttype','in',['date','datetime']),('model_id','=',model_id)]"),
        'on_date_range': fields.integer('Delay'),
        'on_date_range_type': fields.selection([('minutes', 'Minutes'), ('hours', 'Hours'), ('work_days', 'Work Days'), ('days', 'Days'), ('weeks', 'Weeks'), ('months', 'Months')], 'Delay Type'),
        'on_date_range_operand': fields.selection([('after', 'After'), ('before', 'Before')], 'Delay Operand'),
        'interval_number': fields.integer('Interval Number'),
        'interval_type': fields.selection([('minutes', 'Minutes'), ('hours', 'Hours'), ('work_days', 'Work Days'), ('days', 'Days'), ('weeks', 'Weeks'), ('months', 'Months')], 'Interval Unit'),
        'nextcall': fields.datetime("Next Call"),
        'filter_ids': fields.one2many('sartre.filter', 'trigger_id', "Filters", help="The trigger is satisfied if all filters are True"),
        'domain_force': fields.char('Force Domain', size=250),
        'action_ids': fields.many2many('ir.actions.server', 'sartre_trigger_server_action_rel', 'trigger_id', 'action_id', "Actions"),
        'executions_max_number': fields.integer('Max executions', help="Number of time actions are runned,\0 indicates that actions will always be executed"),
    }

    _defaults = {
        'active': lambda * a: True,
        'on_function_type': lambda * a: 'both',
        'on_date_type_display1': lambda * a: 'create_date',
        'on_date_range': lambda * a: 2,
        'on_date_range_type': lambda * a: 'days',
        'on_date_range_operand': lambda * a: 'after',
        'interval_number': lambda * a: 1,
        'interval_type': lambda * a: 'hours',
        'nextcall': lambda * a: now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    def _update_triggers_cache(self, cr):
        self.sartre_triggers_cache = {}
        trigger_ids = self.search(cr, 1, [], context={'active_test': True})
        triggers = self.browse(cr, 1, trigger_ids)
        for trigger in triggers:
            for method in ['create', 'write', 'unlink', 'function', 'other']: # All except for date
                if getattr(trigger, 'on_' + method):
                    self.sartre_triggers_cache.setdefault(method, {}).setdefault(trigger.model_id.model, []).append(trigger.id)
                    if method == 'other':
                        m_class = self.pool.get(trigger.model_id.model)
                        m_name = trigger.on_orther_method_id.name
                        if hasattr(m_class, m_name):
                            setattr(m_class, m_name, sartre_decorator(getattr(m_class, m_name)))
        return True

    def sartre_trigger_decorator(fnct):
        def new_fnct(self, cr, *args, **kwds):
            result = getattr(osv.osv, fnct.__name__)(self, cr, *args, **kwds)
            if result:
                self._update_triggers_cache(cr)
            return result
        return new_fnct

    @sartre_trigger_decorator
    def create(self, cr, uid, vals, context={}):
        return super(sartre_trigger, self).create(cr, uid, vals, context)

    @sartre_trigger_decorator
    def write(self, cr, uid, ids, vals, context={}):
        return super(sartre_trigger, self).write(cr, uid, ids, vals, context)

    @sartre_trigger_decorator
    def unlink(self, cr, uid, ids, context={}):
        return super(sartre_trigger, self).unlink(cr, uid, ids, context)

    def _add_trigger_date_filter(self, cr, uid, trigger, context={}):
        """Build trigger date filter"""
        res = False
        if trigger.on_date:
            interval_number = trigger.on_date_range
            interval_type = str(trigger.on_date_range_type)
            interval_operand = trigger.on_date_range_operand
            # Update trigger next call
            self.write(cr, uid, trigger.id, {'nextcall': now() + RelativeDateTime(**{str(trigger.interval_type): trigger.interval_number})}, context)
            # Add datetime filter
            field = trigger.on_date_type
            limit_date = now()
            if interval_operand == 'after':
                limit_date -= RelativeDateTime(**{interval_type: interval_number})
            if interval_operand == 'before':
                limit_date += RelativeDateTime(**{interval_type: interval_number})
            res = (field, '<=', limit_date.strftime("%Y-%m-%d %H:%M:%S"))
        return res

    def _add_max_executions_filter(self, cr, uid, trigger, context={}):
        """Build max executions filter"""
        res = False
        if trigger.executions_max_number:
            execution_pool = self.pool.get('sartre.execution')
            execution_ids = execution_pool.search(cr, uid, [('trigger_id', '=', trigger.id), ('executions_number', '>=', trigger.executions_max_number)])
            res_ids = list(set(context.get('active_object_ids', [])) - set([execution['res_id'] for execution in execution_pool.read(cr, uid, execution_ids, ['res_id'])]))
            res = ('id', 'in', res_ids)
        return res

    def _build_domain_expression(self, cr, uid, trigger, context={}):
        """Build domain expression"""
        # To manage planned execution
        if not context.get('active_object_ids', []):
            context['active_object_ids'] = self.pool.get(trigger.model_id.model).search(cr, uid, [], context=context)
        operators_cache = self.pool.get('sartre.operator').sartre_operators_cache
        # Define domain from domain_force
        domain = trigger.domain_force and eval(trigger.domain_force.replace('%today', now().strftime('%Y-%m-%d %H:%M:%S'))) or []
        # Add filters one by one if domain_force is empty
        if not domain:
            domain.extend(sum(map(lambda cond: eval(cond.domain.replace('%today', now().strftime('%Y-%m-%d %H:%M:%S'))), trigger.filter_ids), []))
        # Add general filters
        domain.extend(filter(bool, [getattr(self, filter_name)(cr, uid, trigger, context) for filter_name in ['_add_trigger_date_filter', '_add_max_executions_filter']]))
        # To avoid infinite recursion
        if 'triggers' in context and trigger.id in context['triggers']:
            context['active_object_ids'] = list(set(context['active_object_ids']) - set(context['triggers'][trigger.id]))
        # Check if active objects respect all filters based on old or dynamic values, or Python operators
        indexes = [domain.index(item) for item in domain if isinstance(item, tuple) and (item[0].startswith('OLD_') or operators_cache[item[1]].native_operator == 'none' or re.match('(\[\[.+?\]\])', str(item[2]) or ''))]
        if not indexes:
            domain.append(('id', 'in', context['active_object_ids']))
        else:
            fields = [domain[index][0].replace('OLD_', '') for index in indexes]
            old_values = context.get('old_values', {})
            current_values = _get_browse_record_dict(self.pool.get(trigger.model_id.model), cr, uid, context['active_object_ids'])
            # Replace filters on old values or Python operators by filters on active objects
            for index in indexes:
                active_object_ids = list(set(context['active_object_ids']))
                condition = domain[index]
                field = condition[0].replace('OLD_', '')
                prefix = ''
                operator_symbol = condition[1]
                if operator_symbol.startswith('not '): # Can accept 'not ==' instead of '<>' but can't accept '!='
                    prefix = 'not '
                    operator_symbol = operator_symbol.replace('not ', '')
                prefix += operator_symbol == operators_cache[condition[1]].opposite_symbol and 'not ' or '' # += rather than = in order to manage double negation
                other_value = condition[2]
                match = other_value and re.match('(\[\[.+?\]\])', other_value)
                for object_id in list(active_object_ids):
                    if match:
                        other_value = eval(str(match.group()[2:-2]).strip(), {
                            'object': self.pool.get(trigger.model_id.model).browse(cr, uid, object_id),
                            'context': context,
                            'time':time, })
                    current_field_value = current_values.get(object_id, {}).get(field, False)
                    old_field_value = current_field_value
                    if object_id in old_values and field in old_values[object_id]:
                        old_field_value = old_values[object_id][field]
                    localdict = {'selected_field_value': 'OLD_' in condition[0] and old_field_value or current_field_value,
                                 'current_field_value': current_field_value,
                                 'old_field_value': old_field_value,
                                 'other_value': other_value}
                    exec operators_cache[operator_symbol].expression in localdict
                    if 'result' not in localdict or ('result' in localdict and (prefix and localdict['result'] or not localdict['result'])):
                        active_object_ids.remove(object_id)
                domain[index] = ('id', 'in', active_object_ids)
        return domain

    def run_now(self, cr, uid, ids, context=None):
        """Execute now server actions"""
        if context is None:
            context_copy = {}
        else:
            context_copy = dict(context)
        context_copy.setdefault('active_test', False)
        for trigger in self.browse(cr, uid, ids):
            self.logger.notifyChannel('sartre.trigger', netsvc.LOG_DEBUG, 'trigger: %s, User: %s' % (trigger.id, uid))
            domain = []
            domain_built = False
            try:
                # Build domain expression
                domain = self._build_domain_expression(cr, uid, trigger, context_copy)
                domain_built = True
            except Exception, e:
                stack = traceback.format_exc()
                self.pool.get('sartre.exception').create(cr, uid, {'trigger_id': trigger.id, 'exception_type': 'filter', 'exception': tools.ustr(e), 'stack': tools.ustr(stack)})
                self.logger.notifyChannel('sartre.trigger', netsvc.LOG_ERROR, 'Trigger: %s, User: %s, Exception:%s' % (trigger.id, uid, tools.ustr(e)))
            # Search action to execute for filtered objects from domain
            if domain_built:
                # Search objects which validate trigger filters
                trigger_object_ids = self.pool.get(trigger.model_id.model).search(cr, uid, domain, context=context_copy)
                # Execute server actions
                if trigger_object_ids:
                    context_copy.setdefault('triggers', {}).setdefault(trigger.id, []).extend(trigger_object_ids)
                    ir_actions_server_pool = self.pool.get('ir.actions.server')
                    for action in trigger.action_ids:
                        if action.active:
                            try:
                                if action.run_once:
                                    # Sartre case where you run once for all instances
                                    context_copy['active_id'] = trigger_object_ids
                                    ir_actions_server_pool.run(cr, action.user_id and action.user_id.id or uid, [action.id], context=context_copy)
                                    self.logger.notifyChannel('ir.actions.server', netsvc.LOG_DEBUG, 'Action: %s, User: %s, Resource: %s, Origin: sartre.trigger,%s' % (action.id, action.user_id and action.user_id.id or uid, context_copy['active_id'], trigger.id))
                                else:
                                    # Sartre case where you run once per instance
                                    for object_id in trigger_object_ids:
                                        context_copy['active_id'] = object_id
                                        ir_actions_server_pool.run(cr, action.user_id and action.user_id.id or uid, [action.id], context=context_copy)
                                        self.logger.notifyChannel('ir.actions.server', netsvc.LOG_DEBUG, 'Action: %s, User: %s, Resource: %s, Origin: sartre.trigger,%s' % (action.id, action.user_id and action.user_id.id or uid, context_copy['active_id'], trigger.id))
                                if trigger.executions_max_number:
                                    for object_id in trigger_object_ids:
                                        self.pool.get('sartre.execution').update_executions_counter(cr, uid, trigger, object_id)
                            except Exception, e:
                                stack = traceback.format_exc()
                                self.pool.get('sartre.exception').create(cr, uid, {'trigger_id': trigger.id, 'exception_type': 'action', 'res_id': False, 'action_id': action.id, 'exception': tools.ustr(e), 'stack': tools.ustr(stack)})
                                self.logger.notifyChannel('ir.actions.server', netsvc.LOG_ERROR, 'Action: %s, User: %s, Resource: %s, Origin: sartre.trigger,%s, Exception: %s' % (action.id, action.user_id and action.user_id.id or uid, False, trigger.id, tools.ustr(e)))
                                continue
        return True

    def check_triggers(self, cr, uid, context={}):
        """Call the scheduler to check date based trigger triggers"""
        # Search triggers to execute
        trigger_ids = self.search(cr, uid, [('active', '=', True), ('on_date', '=', True), ('nextcall', '<=', now().strftime("%Y-%m-%d %H:%M:%S"))])
        if trigger_ids:
            # Launch triggers execution
            self.run_now(cr, uid, trigger_ids, context)
        return True

sartre_trigger()

class sartre_filter(osv.osv):
    _name = 'sartre.filter'
    _description = 'Sartre Filter'
    _rec_name = 'field_id'

    def onchange_get_domain(self, cr, uid, ids, field='', operator_id=False, opposite=False, value='', value_age='current', value_type='static', context={}):
        """Build domain expression from filter items"""
        res = {}
        operator_pool = self.pool.get('sartre.operator')
        if field and operator_id and (value or not operator_pool.read(cr, uid, operator_id, ['other_value_necessary'])['other_value_necessary']):
            field_name = (value_age == 'old' and 'OLD_' or '') + field
            operator = operator_pool.browse(cr, uid, operator_id)
            symbol = opposite and operator.opposite_symbol or operator.symbol
            if not isinstance(value, (str, unicode)):
                value = ''
            if value_age == 'current' and value_type == 'static':
                value = operator.other_value_transformation and eval(operator.other_value_transformation, {'value': value}) or value
            if value_type == 'dynamic' and value:
                value = '[[ object.' + value + ' ]]'
            res['value'] = {'domain': str([(field_name, symbol, value)])}
        return res

    def _build_field_expression(self, cr, uid, field_id, field_expression='', context={}):
        """Build field expression"""
        field_pool = self.pool.get('ir.model.fields')
        field_obj = field_pool.read(cr, uid, field_id, ['name', 'ttype', 'relation', 'model'])
        field_expr = field_expression and (field_expression.split('.')[:-1] and '.'.join(field_expression.split('.')[:-1]) or field_expression) + '.' or ''
        obj = self.pool.get(field_obj['model'])
        if field_obj['name'] in obj._columns and 'fields.related' in str(obj._columns[field_obj['name']]):
            field_expr += obj._columns[field_obj['name']].arg[0] + '.'
        field_expr += field_obj['name']
        if field_obj['ttype'] in ['many2one', 'one2many', 'many2many']:
            field_expr += field_obj['ttype'] == 'many2one' and '.'  or ''
            field_expr += field_obj['ttype'] in ['one2many', 'many2many'] and '[0].' or ''
            field_expr += self.pool.get(field_obj['relation'])._rec_name
        return field_expr

    def _check_field_expression(self, cr, uid, model_id, field_expression='', context={}):
        """Check field expression"""
        field_list = field_expression and (field_expression.split('.')[:-1] or [field_expression])
        if field_list:
            field_pool = self.pool.get('ir.model.fields')
            model = self.pool.get('ir.model').read(cr, uid, model_id, ['model'])['model']
            i = 0
            for f_name in field_list:
                f_id = field_pool.search(cr, uid, [('model', '=', model), ('name', '=', '[' in f_name and f_name[:f_name.index('[')] or f_name)], limit=1)
                if not f_id:
                    raise osv.except_osv(_('Error'), _("The field %s is not in the model %s !" % (f_name, model)))
                f_obj = field_pool.read(cr, uid, f_id[0], ['name', 'ttype', 'relation'])
                if f_obj['ttype'] in ['many2one', 'one2many', 'many2many']:
                    model = f_obj['relation']
                    model_id = self.pool.get('ir.model').search(cr, uid, [('model', '=', model)], limit=1)[0]
                elif len(field_expression.split('.')) > 1 and  i < len(field_list):
                    raise osv.except_osv(_('Error'), _("The field %s is not a relation field !" % f_obj['name']))
                i += 1
        return model_id

    def onchange_get_field_domain(self, cr, uid, ids, model_id, field_expression='', context={}):
        """Get field domain"""
        model_id = self._check_field_expression(cr, uid, model_id, field_expression, context)
        res = {'values': {'field_id': False}, 'domain': {'field_id': "[('model_id', '=', %d)]" % (model_id,)}}
        return res

    def onchange_get_field_expression(self, cr, uid, ids, model_id, field_expression='', field_id=False, context={}):
        """Update the field expression"""
        new_field_expression = field_expression
        if field_id:
            new_field_expression = self._build_field_expression(cr, uid, field_id, field_expression, context)
        res = self.onchange_get_field_domain(cr, uid, ids, model_id, new_field_expression, context)
        res.setdefault('value', {}).update({'field_expression': new_field_expression})
        return res

    def onchange_get_value_age_domain(self, cr, uid, ids, field='', operator_id=False, opposite=False, value='', value_age='current', value_type='static', context={}):
        """Update the field 'value_age'"""
        value_age_filter = operator_id and self.pool.get('sartre.operator').read(cr, uid, operator_id, ['value_age_filter'])['value_age_filter']
        if value_age_filter != 'both':
            value_age = value_age_filter
        res = self.onchange_get_domain(cr, uid, ids, field, operator_id, opposite, value, value_age, value_type, context)
        res.setdefault('value', {})
        res['value'] = {'value_age': value_age, 'value_age_readonly': value_age_filter != 'both'}
        return res

    _columns = {
        "trigger_id": fields.many2one('sartre.trigger', "Trigger", required=True, ondelete='cascade'),
        "field_name": fields.char("Field", size=256),
        "value_age": fields.selection([
            ('current', 'Current Value'),
            ('old', 'Old Value'),
        ], "Value Age", select=True),
        "value_age_readonly": fields.boolean("Value Age Readonly"),
        "operator_id": fields.many2one('sartre.operator', "Operator"),
        "opposite": fields.boolean('Opposite'),
        "value": fields.char("Value", size=128, help="Dynamic value corresponds to an object field"),
        "value_type": fields.selection([('static', 'Static'), ('dynamic', 'Dynamic')], "Value Type"),
        "domain": fields.char("Domain", size=256, required=True),
        "field_id": fields.many2one('ir.model.fields', "Field Builder"),
        "field_expression": fields.char("Expression to copy", size=256),
    }

    _defaults = {
        'value_age': lambda * a: 'current',
        'value_type': lambda * a: 'static',
    }

sartre_filter()

class sartre_exception(osv.osv):
    _name = 'sartre.exception'
    _description = 'Sartre Exception'
    _rec_name = 'trigger_id'

    _columns = {
        'trigger_id': fields.many2one('sartre.trigger', 'Trigger', required=False, select=True, ondelete='cascade'),
        'exception_type': fields.selection([
            ('filter', 'Filter'),
            ('action', 'Action'),
             ], 'Type', required=False, select=True),
        'res_id': fields.integer('Resource', required=False),
        'action_id': fields.many2one('ir.actions.server', 'Action', required=False, select=True),
        'exception': fields.text('Exception', required=False),
        'stack': fields.text('Stack Trace', required=False),
        'create_date': fields.datetime('Creation Date'),
    }

    _order = "create_date desc"

sartre_exception()

class sartre_execution(osv.osv):
    _name = 'sartre.execution'
    _description = 'Sartre Execution'
    _rec_name = 'trigger_id'

    _columns = {
        'trigger_id': fields.many2one('sartre.trigger', 'Trigger', required=False, select=True, ondelete='cascade'),
        'model_id': fields.many2one('ir.model', 'Object', required=False, select=True),
        'res_id': fields.integer('Resource', required=False),
        'executions_number': fields.integer('Executions'),
    }

    def update_executions_counter(self, cr, uid, trigger, res_id):
        """Update executions counter"""
        if not (trigger and res_id):
            raise osv.except_osv(_('Error'), _('Sartre Execution: all arguments are mandatory !'))
        log_id = self.search(cr, uid, [('trigger_id', '=', trigger.id), ('model_id', '=', trigger.model_id.id), ('res_id', '=', res_id)], limit=1)
        if log_id:
            executions_number = self.read(cr, uid, log_id[0], ['executions_number'])['executions_number'] + 1
            return self.write(cr, uid, log_id[0], {'executions_number': executions_number})
        else:
            return self.create(cr, uid, {'trigger_id': trigger.id, 'model_id': trigger.model_id.id, 'res_id': res_id, 'executions_number': 1}) and True

sartre_execution()

def _check_method_based_triggers(self, cr, uid, method, field_name='', calculation_method=False):
    """Check method based trigger triggers"""
    trigger_ids = []
    trigger_obj = hasattr(self, 'pool') and self.pool.get('sartre.trigger') or pooler.get_pool(cr.dbname).get('sartre.trigger')
    if trigger_obj:
        # Search triggers to execute
        trigger_ids = hasattr(trigger_obj, 'sartre_triggers_cache') and trigger_obj.sartre_triggers_cache.get(method, {}).get(self._name, [])
        if method == 'function':
            for trigger_id in trigger_ids:
                trigger = trigger_obj.browse(cr, uid, trigger_id)
                if not (trigger.on_function_field_id.name == field_name and trigger.on_function_type in [method, 'both']):
                    trigger_ids.remove(trigger_id)
    return trigger_ids

def sartre_decorator(original_method):
    def sartre_trigger(*args, **kwds):
        # Get arguments
        method_name = original_method.__name__
        args_names = inspect.getargspec(original_method)[0]
        args_dict = {}.fromkeys(args_names, False)
        for arg in args_names:
            if args_names.index(arg) < len(args):
                args_dict[arg] = args[args_names.index(arg)]
        self = args_dict.get('obj', False) or args_dict.get('self', False)
        cr = args_dict.get('cursor', False) or args_dict.get('cr', False)
        uid = args_dict.get('uid', False) or args_dict.get('user', False)
        ids = args_dict.get('ids', []) or args_dict.get('id', [])
        if isinstance(ids, (int, long)):
            ids = [ids]
        context = dict(args_dict.get('context', {}) or {})
        args_ok = reduce(operator.__and__, map(bool, [self, cr, uid]))
        if args_ok:
            # Case: trigger on function
            field_name = ''
            calculation_method = False
            if method_name in ('get', 'set') and original_method.im_class == fields.function:
                field_name = args_dict.get('name', '')
                calculation_method = method_name
                method_name = 'function'
            # Search triggers
            trigger_ids = _check_method_based_triggers(self, cr, uid, method_name, field_name, calculation_method)
            # Save old values if triggers exist
            if trigger_ids and ids:
                context.update({'active_object_ids': ids, 'old_values': _get_browse_record_dict(self, cr, uid, ids)})
                # Case: trigger on unlink
                if method_name == 'unlink':
                    self.pool.get('sartre.trigger').run_now(cr, uid, trigger_ids, context=context)
        # Execute original method
        result = original_method(*args, **kwds)
        # Run triggers if exists
        if result and args_ok and trigger_ids and method_name != 'unlink':
            # Case: trigger on create
            if method_name == 'create':
                context['active_object_ids'] = [result]
            self.pool.get('sartre.trigger').run_now(cr, uid, trigger_ids, context=context)
        return result
    return sartre_trigger

for method in [orm.orm.create, orm.orm.write, orm.orm.unlink, fields.function.get, fields.function.set]:
    if hasattr(method.im_class, method.__name__):
        setattr(method.im_class, method.__name__, sartre_decorator(getattr(method.im_class, method.__name__)))
